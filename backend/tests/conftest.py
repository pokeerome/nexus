import hashlib
import os
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

# ---------------------------------------------------------------------------
# Safety first: these tests create users, files and chunks.
# They must NEVER run against your real database.
# ---------------------------------------------------------------------------
_env = dotenv_values(".env")
TEST_URL = os.environ.get("TEST_DATABASE_URL") or _env.get("TEST_DATABASE_URL")
REAL_URL = os.environ.get("DATABASE_URL") or _env.get("DATABASE_URL")

if not TEST_URL:
    pytest.exit(
        "TEST_DATABASE_URL is missing. Add it to backend/.env (use a separate Neon branch).",
        returncode=2,
    )
if REAL_URL:
    a, b = make_url(TEST_URL), make_url(REAL_URL)
    if (a.host, a.database) == (b.host, b.database):
        pytest.exit(
            "TEST_DATABASE_URL points to the same database as DATABASE_URL. Stopping.",
            returncode=2,
        )

os.environ["DATABASE_URL"] = TEST_URL
os.environ["CELERY_EAGER"] = "1"  # run file reading inside the request, no Redis needed
os.environ["SEARCH_MODE"] = "hybrid"  # no reranker model needed
os.environ["RATE_LIMITS"] = "off"  # most tests make many requests; the rate-limit tests turn it on
os.environ["REDIS_URL"] = ""  # tests count requests in memory, never in your real Redis
os.environ.setdefault("OPENAI_API_KEY", "not-used-in-tests")


def fake_embed_texts(texts):
    """Same text -> same vector. No OpenAI calls, no cost."""
    vectors = []
    for t in texts:
        digest = hashlib.sha256(t.encode()).digest()
        base = [(b - 128) / 128 for b in digest]
        vectors.append((base * 48)[:1536])
    return vectors


@pytest.fixture(scope="session", autouse=True)
def prepare_database(tmp_path_factory):
    from sqlalchemy import text

    import ingest
    import main
    import models  # noqa: F401
    import search
    from database import Base, engine

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS search_vector tsvector "
                "GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS chunks_search_idx ON chunks USING GIN (search_vector)")
        )

    patcher = pytest.MonkeyPatch()
    patcher.setattr(ingest, "embed_texts", fake_embed_texts)
    patcher.setattr(search, "embed_texts", fake_embed_texts)
    patcher.setattr(main, "UPLOAD_DIR", Path(tmp_path_factory.mktemp("uploads")))
    yield
    patcher.undo()


@pytest.fixture(scope="session")
def client(prepare_database):
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app, base_url="http://127.0.0.1:8000") as c:  # "with" also starts the MCP tool server
        yield c


class TestUser:
    __test__ = False  # tell pytest this is not a test class

    def __init__(self, email, headers, user_id, workspace_id):
        self.email = email
        self.headers = headers
        self.user_id = user_id
        self.workspace_id = workspace_id


@pytest.fixture
def new_user(client):
    def make(label="user"):
        email = f"{label}-{uuid.uuid4().hex[:8]}@example.com"
        r = client.post(
            "/auth/signup",
            json={"email": email, "password": "password123", "workspace_name": f"{label} space"},
        )
        assert r.status_code == 200, r.text
        headers = {"Authorization": "Bearer " + r.json()["access_token"]}
        me = client.get("/auth/me", headers=headers).json()
        return TestUser(email, headers, me["id"], me["workspaces"][0]["id"])

    return make


@pytest.fixture
def upload(client):
    def do(user, workspace_id, filename, text):
        return client.post(
            f"/workspaces/{workspace_id}/documents",
            headers=user.headers,
            files={"file": (filename, text.encode())},
        )

    return do