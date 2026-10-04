import os
import tempfile

from flashrank import Ranker, RerankRequest

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from embeddings import embed_texts
from models import Chunk, Document

RRF_K = 60
CANDIDATES = 20


def to_dict(chunk, filename, score):
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "filename": filename,
        "chunk_index": chunk.chunk_index,
        "content": chunk.content,
        "score": round(score, 4),
    }


def vector_search(db: Session, workspace_id: int, query: str, limit: int = CANDIDATES):
    query_vector = embed_texts([query])[0]
    distance = Chunk.embedding.cosine_distance(query_vector)

    rows = db.execute(
        select(Chunk, Document.filename, distance.label("distance"))
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.workspace_id == workspace_id)
        .order_by(distance)
        .limit(limit)
    ).all()

    return [to_dict(chunk, filename, 1 - dist) for chunk, filename, dist in rows]


def keyword_search(db: Session, workspace_id: int, query: str, limit: int = CANDIDATES):
    sql = text(
        """
        SELECT c.id, ts_rank(c.search_vector, q.tsq) AS rank
        FROM chunks c,
             LATERAL (
               SELECT CAST(
                 replace(CAST(websearch_to_tsquery('english', :query) AS text), ' & ', ' | ')
                 AS tsquery
               ) AS tsq
             ) q
        WHERE c.workspace_id = :workspace_id AND c.search_vector @@ q.tsq
        ORDER BY rank DESC
        LIMIT :limit
        """
    )
    rows = db.execute(
        sql, {"query": query, "workspace_id": workspace_id, "limit": limit}
    ).all()
    if not rows:
        return []

    ranks = {r.id: r.rank for r in rows}
    chunk_rows = db.execute(
        select(Chunk, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id.in_(list(ranks)))
    ).all()

    hits = [to_dict(chunk, filename, ranks[chunk.id]) for chunk, filename in chunk_rows]
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits


def hybrid_search(db: Session, workspace_id: int, query: str, limit: int = 5):
    vector_hits = vector_search(db, workspace_id, query)
    keyword_hits = keyword_search(db, workspace_id, query)

    scores = {}
    items = {}
    for hits in (vector_hits, keyword_hits):
        for rank, hit in enumerate(hits, start=1):
            scores[hit["id"]] = scores.get(hit["id"], 0) + 1 / (RRF_K + rank)
            items[hit["id"]] = hit

    best_ids = sorted(scores, key=scores.get, reverse=True)[:limit]
    return [{**items[i], "score": round(scores[i], 4)} for i in best_ids]

_ranker = None


def get_ranker():
    global _ranker
    if _ranker is None:
        _ranker = Ranker(
            model_name="ms-marco-MiniLM-L-12-v2",
            cache_dir=os.path.join(tempfile.gettempdir(), "flashrank"),
        )
    return _ranker


def rerank_search(db: Session, workspace_id: int, query: str, limit: int = 5):
    candidates = hybrid_search(db, workspace_id, query, limit=15)
    if not candidates:
        return []

    passages = [{"id": c["id"], "text": c["content"]} for c in candidates]
    ranked = get_ranker().rerank(RerankRequest(query=query, passages=passages))

    by_id = {c["id"]: c for c in candidates}
    return [
        {**by_id[r["id"]], "score": round(float(r["score"]), 4)}
        for r in ranked[:limit]
    ]


def search_chunks(
    db: Session, workspace_id: int, query: str, limit: int = 5, mode: str = "rerank"
):
    if mode == "vector":
        return vector_search(db, workspace_id, query, limit)
    if mode == "hybrid":
        return hybrid_search(db, workspace_id, query, limit)
    return rerank_search(db, workspace_id, query, limit)