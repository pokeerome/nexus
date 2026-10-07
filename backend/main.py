import contextlib
import json
import os
import uuid
from pathlib import Path

from chat import rewrite_query, stream_answer
from database import get_db
from deps import get_current_user, require_membership, require_role
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from mcp_server import mcp
from memlog import log_memory
from models import Chunk, Document, Membership, User, Workspace
from schemas import (
    ChatRequest,
    LoginRequest,
    MemberAdd,
    MemberRoleUpdate,
    SearchRequest,
    SignupRequest,
    TokenResponse,
)
from search import search_chunks
from security import (
    create_access_token,
    create_mcp_token,
    hash_password,
    verify_password,
)
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from tasks import ingest_document_task


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        log_memory("app started")
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/mcp", mcp.streamable_http_app())

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
    membership: Membership = Depends(require_role("member")),
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
    membership: Membership = Depends(require_role("member")),
    db: Session = Depends(get_db),
):
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.workspace_id == workspace_id
        )
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if membership.role != "owner" and doc.uploaded_by != membership.user_id:
        raise HTTPException(
            status_code=403, detail="You can only remove files that you uploaded"
        )

    stored_path = doc.stored_path
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    db.delete(doc)
    db.commit()

    try:
        Path(stored_path).unlink(missing_ok=True)
    except OSError:
        pass

    return {"deleted": document_id}

@app.post("/workspaces/{workspace_id}/agent")
async def agent_chat(
    workspace_id: int,
    data: ChatRequest,
    membership: Membership = Depends(require_membership),
):
    from agent import get_model, stream_agent_events
    from langchain_core.messages import AIMessage, HumanMessage

    token = create_mcp_token(membership.user_id, workspace_id)
    mcp_url = os.getenv("MCP_URL", f"http://127.0.0.1:{os.getenv('PORT', '8000')}/mcp/")

    messages = [
        (HumanMessage if m.role == "user" else AIMessage)(content=m.content)
        for m in data.history[-6:]
    ]
    messages.append(HumanMessage(content=data.question))

    async def event_stream():
        log_memory("agent request start")
        try:
            async for event in stream_agent_events(get_model(), mcp_url, token, messages):
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            log_memory("agent request end")
    return StreamingResponse(event_stream(), media_type="text/event-stream")

def count_owners(db: Session, workspace_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.workspace_id == workspace_id, Membership.role == "owner")
    )


@app.get("/workspaces/{workspace_id}/members")
def list_members(
    workspace_id: int,
    membership: Membership = Depends(require_membership),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(User.id, User.email, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == workspace_id)
        .order_by(Membership.id)
    ).all()
    return [{"user_id": r.id, "email": r.email, "role": r.role} for r in rows]


@app.post("/workspaces/{workspace_id}/members")
def add_member(
    workspace_id: int,
    data: MemberAdd,
    membership: Membership = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == data.email))
    if not user:
        raise HTTPException(
            status_code=404, detail="No user with that email. They need to sign up first."
        )

    existing = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.workspace_id == workspace_id
        )
    )
    if existing:
        raise HTTPException(status_code=400, detail="That user is already a member")

    db.add(Membership(user_id=user.id, workspace_id=workspace_id, role=data.role))
    db.commit()
    return {"user_id": user.id, "email": user.email, "role": data.role}


@app.patch("/workspaces/{workspace_id}/members/{user_id}")
def change_member_role(
    workspace_id: int,
    user_id: int,
    data: MemberRoleUpdate,
    membership: Membership = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    target = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id, Membership.workspace_id == workspace_id
        )
    )
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.role == "owner" and data.role != "owner" and count_owners(db, workspace_id) <= 1:
        raise HTTPException(status_code=400, detail="A workspace needs at least one owner")

    target.role = data.role
    db.commit()
    return {"user_id": user_id, "role": data.role}


@app.delete("/workspaces/{workspace_id}/members/{user_id}")
def remove_member(
    workspace_id: int,
    user_id: int,
    membership: Membership = Depends(require_membership),
    db: Session = Depends(get_db),
):
    # Owners can remove anyone. Everyone else can only remove themselves (leave).
    if user_id != membership.user_id and membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can remove other members")

    target = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id, Membership.workspace_id == workspace_id
        )
    )
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.role == "owner" and count_owners(db, workspace_id) <= 1:
        raise HTTPException(status_code=400, detail="A workspace needs at least one owner")

    db.delete(target)
    db.commit()
    return {"removed": user_id}