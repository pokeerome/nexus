import anyio
import jwt
from database import SessionLocal
from mcp.server.fastmcp import Context, FastMCP
from models import Document
from safety import new_nonce, safe_filename, wrap_passage
from security import decode_mcp_token
from sqlalchemy import select


mcp = FastMCP(
    "Nexus Tools",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


def get_workspace_id(ctx: Context) -> int:
    """Read the workspace from the signed token, never from the AI's own arguments."""
    request = ctx.request_context.request
    auth = request.headers.get("authorization", "") if request is not None else ""
    if not auth.lower().startswith("bearer "):
        raise ValueError("Missing token")
    try:
        payload = decode_mcp_token(auth[7:])
    except jwt.PyJWTError:
        raise ValueError("Invalid or expired token")
    return int(payload["ws"])


def _list_documents(workspace_id: int) -> list[dict]:
    db = SessionLocal()
    try:
        docs = db.scalars(
            select(Document)
            .where(Document.workspace_id == workspace_id)
            .order_by(Document.created_at.desc())
        ).all()
        return [{"filename": safe_filename(d.filename), "status": d.status} for d in docs]
    finally:
        db.close()


def _search(workspace_id: int, query: str, limit: int) -> list[dict]:
    from search import search_chunks

    db = SessionLocal()
    try:
        hits = search_chunks(db, workspace_id, query, limit=limit)
        nonce = new_nonce()
        return [
            {
                "filename": safe_filename(h["filename"]),
                "text": wrap_passage(nonce, h["filename"], h["content"]),
            }
            for h in hits
        ]
    finally:
        db.close()


@mcp.tool()
async def list_documents(ctx: Context) -> list[dict]:
    """List the files in the user's workspace and whether each one is ready to search."""
    workspace_id = get_workspace_id(ctx)
    return await anyio.to_thread.run_sync(_list_documents, workspace_id)


@mcp.tool()
async def search_documents(query: str, ctx: Context, limit: int = 5) -> list[dict]:
    """Search the user's documents. Returns the best matching passages with their file names."""
    workspace_id = get_workspace_id(ctx)
    limit = max(1, min(limit, 8))
    return await anyio.to_thread.run_sync(_search, workspace_id, query, limit)