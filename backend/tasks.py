import os

from celery import Celery
from database import SessionLocal
from ingest import ingest_document
from memlog import log_memory
from models import Document

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("nexus", broker=REDIS_URL)
celery_app.conf.update(
    task_always_eager=os.getenv("CELERY_EAGER", "0") == "1",
    task_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
)


@celery_app.task(name="ingest_document")
def ingest_document_task(document_id: int):
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return
        ingest_document(db, doc)
        log_memory(f"ingest finished ({doc.status})")
    finally:
        db.close()