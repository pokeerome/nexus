from sqlalchemy import select
from sqlalchemy.orm import Session

from embeddings import embed_texts
from models import Chunk, Document


def search_chunks(db: Session, workspace_id: int, query: str, limit: int = 5):
    query_vector = embed_texts([query])[0]
    distance = Chunk.embedding.cosine_distance(query_vector)

    rows = db.execute(
        select(Chunk, Document.filename, distance.label("distance"))
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.workspace_id == workspace_id)
        .order_by(distance)
        .limit(limit)
    ).all()

    return [
        {
            "document_id": chunk.document_id,
            "filename": filename,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "score": round(1 - dist, 3),
        }
        for chunk, filename, dist in rows
    ]