import json
import os
import uuid
from pathlib import Path

from chat import rewrite_query, stream_answer
from database import get_db
from deps import get_current_user, require_membership
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from models import Chunk, Document, Membership, User, Workspace
from schemas import (
    ChatRequest,
    LoginRequest,
    SearchRequest,
    SignupRequest,
    TokenResponse,
)
from search import search_chunks
from security import create_access_token, hash_password, verify_password
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from tasks import ingest_document_task

app = FastAPI()

UPLOAD_DIR = Path("uploads")
ALLOWED_TYPES = {".pdf", ".txt", ".md", ".docx", ".csv"}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB

origins = [
    o.strip()
    for o in os.getenv("FRONTEND_URL", "http://localhost:5173").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins + ["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/signup", response_model=TokenResponse)
def signup(data: SignupRequest, db: Session = Depends(get_db)):
    existing = db.scalar(select(User).where(User.email == data.email))
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(email=data.email, hashed_password=hash_password(data.password))
    workspace = Workspace(name=data.workspace_name)
    db.add_all([user, workspace])
    db.flush()

    db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    db.commit()

    return TokenResponse(access_token=create_access_token(user.id))


@app.post("/auth/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email))
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Wrong email or password")

    return TokenResponse(access_token=create_access_token(user.id))

@app.get("/auth/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Workspace.id, Workspace.name, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id)
    ).all()

    return {
        "id": user.id,
        "email": user.email,
        "workspaces": [
            {"id": r.id, "name": r.name, "role": r.role} for r in rows
        ],
    }

def doc_to_dict(doc: Document):
    return {
        "id": doc.id,
        "filename": doc.filename,
        "size_bytes": doc.size_bytes,
        "status": doc.status,
        "error": doc.error_message,
        "created_at": doc.created_at,
    }


@app.post("/workspaces/{workspace_id}/documents")
def upload_document(
    workspace_id: int,
    file: UploadFile = File(...),
    membership: Membership = Depends(require_membership),
    db: Session = Depends(get_db),
):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Only PDF, TXT, MD, DOCX, CSV files are allowed")

    content = file.file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="File is too big (max 10 MB)")

    folder = UPLOAD_DIR / str(workspace_id)
    folder.mkdir(parents=True, exist_ok=True)
    stored_path = folder / f"{uuid.uuid4().hex}{ext}"
    stored_path.write_bytes(content)

    doc = Document(
        workspace_id=workspace_id,
        uploaded_by=membership.user_id,
        filename=file.filename,
        stored_path=str(stored_path),
        size_bytes=len(content),
        status="queued",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    try:
        ingest_document_task.delay(doc.id)
    except Exception as e:
        doc.status = "failed"
        doc.error_message = "Could not start processing. Please try again."
        db.commit()
        print("Enqueue failed:", e)

    db.refresh(doc)
    return doc_to_dict(doc)


@app.get("/workspaces/{workspace_id}/documents")
def list_documents(
    workspace_id: int,
    membership: Membership = Depends(require_membership),
    db: Session = Depends(get_db),
):
    docs = db.scalars(
        select(Document)
        .where(Document.workspace_id == workspace_id)
        .order_by(Document.created_at.desc())
    ).all()
    return [doc_to_dict(d) for d in docs]

@app.get("/workspaces/{workspace_id}/documents/{document_id}")
def get_document(
    workspace_id: int,
    document_id: int,
    membership: Membership = Depends(require_membership),
    db: Session = Depends(get_db),
):
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.workspace_id == workspace_id
        )
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc_to_dict(doc)

@app.post("/workspaces/{workspace_id}/search")
def search(
    workspace_id: int,
    data: SearchRequest,
    membership: Membership = Depends(require_membership),
    db: Session = Depends(get_db),
):
    return search_chunks(db, workspace_id, data.query, data.limit)

@app.post("/workspaces/{workspace_id}/chat")
def chat(
    workspace_id: int,
    data: ChatRequest,
    membership: Membership = Depends(require_membership),
    db: Session = Depends(get_db),
):
    history = [m.model_dump() for m in data.history][-6:]
    standalone = rewrite_query(history, data.question)
    sources = search_chunks(db, workspace_id, standalone, limit=5)

    def event_stream():
        yield f"data: {json.dumps({'type': 'query', 'data': standalone})}\n\n"
        for event in stream_answer(sources, standalone):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.delete("/workspaces/{workspace_id}/documents/{document_id}")
def delete_document(
    workspace_id: int,
    document_id: int,
    membership: Membership = Depends(require_membership),
    db: Session = Depends(get_db),
):
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.workspace_id == workspace_id
        )
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    stored_path = doc.stored_path
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    db.delete(doc)
    db.commit()

    try:
        Path(stored_path).unlink(missing_ok=True)
    except OSError:
        pass

    return {"deleted": document_id}