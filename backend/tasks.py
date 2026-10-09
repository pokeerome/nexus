import os
import time

from celery import Celery

from database import SessionLocal
from ingest import ingest_document
from metrics import end_request, finish, start_request
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
    info, token = start_request()
    db = SessionLocal()
    status = 200
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return
        info.workspace_id = doc.workspace_id
        info.user_id = doc.uploaded_by
        ingest_document(db, doc)
        if doc.status == "failed":
            status = 422
    except Exception:
        status = 500
        raise
    finally:
        db.close()
        finish(info, "ingest", status)
        end_request(token)