import sys

from sqlalchemy import delete, select

from database import SessionLocal
from ingest import ingest_document
from models import Chunk, Document

workspace_id = int(sys.argv[1])
db = SessionLocal()

docs = db.scalars(select(Document).where(Document.workspace_id == workspace_id)).all()
for doc in docs:
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    db.commit()
    ingest_document(db, doc)
    print(doc.filename, doc.status)