from chunker import chunk_text
from embeddings import embed_texts
from extract import extract_text
from models import Chunk, Document
from safety import clean_text, detect_injection
from sqlalchemy.orm import Session


def make_header(text: str, filename: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    first_line = first_line.lstrip("# ").strip()[:100]
    return f"{filename} | {first_line}" if first_line else filename


def ingest_document(db: Session, doc: Document) -> None:
    try:
        doc.status = "processing"
        doc.error_message = None
        db.commit()

        text, notes = clean_text(extract_text(doc.stored_path))
        notes += detect_injection(text)
        doc.warning = "; ".join(dict.fromkeys(notes))[:500] or None
        pieces = chunk_text(text)
        if not pieces:
            doc.status = "failed"
            doc.error_message = "No readable text found in this file"
            db.commit()
            return

        header = make_header(text, doc.filename)
        pieces = [f"[{header}]\n{piece}" for piece in pieces]

        vectors = embed_texts(pieces)
        for i, (piece, vector) in enumerate(zip(pieces, vectors)):
            db.add(
                Chunk(
                    document_id=doc.id,
                    workspace_id=doc.workspace_id,
                    chunk_index=i,
                    content=piece,
                    embedding=vector,
                )
            )

        doc.status = "ready"
        db.commit()
    except Exception as e:
        db.rollback()
        doc.status = "failed"
        doc.error_message = str(e)[:500]
        db.commit()
        print("Ingest failed:", e)