import json
import re
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from metrics import cost_usd
from security import create_mcp_token
from test_safety import call_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class FakeOpenAI:
    """Pretends to be the AI. It answers with a fixed text and reports token counts."""

    def __init__(self, text, prompt_tokens=120, completion_tokens=30):
        self.text = text

        def create(**kwargs):
            for i in range(0, len(self.text), 9):
                yield NS(choices=[NS(delta=NS(content=self.text[i : i + 9]))], usage=None)
            yield NS(choices=[], usage=NS(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens))

        self.chat = NS(completions=NS(create=create))


class FakeEmbeddings:
    """Pretends to be the embeddings service. Every call 'uses' 1000 tokens."""

    def __init__(self, tokens=1000):
        def create(model, input):
            return NS(
                data=[NS(embedding=[0.1] * 1536) for _ in input],
                usage=NS(total_tokens=tokens),
            )

        self.embeddings = NS(create=create)


def ask(client, user, workspace_id=None, question="what does it cost?"):
    r = client.post(
        f"/workspaces/{workspace_id or user.workspace_id}/chat",
        headers=user.headers,
        json={"question": question},
    )
    assert r.status_code == 200
    return r


def usage_rows(workspace_id, kind=None):
    from database import SessionLocal
    from models import UsageEvent

    db = SessionLocal()
    try:
        query = select(UsageEvent).where(UsageEvent.workspace_id == workspace_id).order_by(UsageEvent.id)
        if kind:
            query = query.where(UsageEvent.kind == kind)
        return db.scalars(query).all()
    finally:
        db.close()


def json_lines(text):
    lines = []
    for line in text.splitlines():
        try:
            lines.append(json.loads(line))
        except ValueError:
            pass
    return lines


@pytest.fixture
def real_embeddings(monkeypatch):
    """Use the real embedding code, with a fake service behind it."""
    import embeddings
    import ingest
    import search

    monkeypatch.setattr(embeddings, "client", FakeEmbeddings())
    monkeypatch.setattr(ingest, "embed_texts", embeddings.embed_texts)
    monkeypatch.setattr(search, "embed_texts", embeddings.embed_texts)


# ---------------------------------------------------------------------------
# Request ids and logs
# ---------------------------------------------------------------------------
def test_every_response_has_its_own_request_id(client):
    ids = {client.get("/health").headers["x-request-id"] for _ in range(3)}
    assert len(ids) == 3
    assert all(re.fullmatch(r"[0-9a-f]{12}", i) for i in ids)


def test_requests_are_logged_as_json_with_ids_only(client, new_user, upload, monkeypatch, capsys):
    import chat

    a = new_user("a")
    capsys.readouterr()  # forget what was printed before

    monkeypatch.setattr(chat, "client", FakeOpenAI("It costs 40 (secret.txt)."))
    upload(a, a.workspace_id, "secret.txt", "TOPSECRETFILETEXT costs 40 pesos")
    r = ask(client, a, question="TOPSECRETQUESTION how much?")

    out = capsys.readouterr().out
    assert "TOPSECRET" not in out  # no questions, no file text in the logs
    assert a.headers["Authorization"].split()[1] not in out  # no login tokens
    assert "password123" not in out

    lines = [l for l in json_lines(out) if l["event"] == "request_finished"]
    chat_line = [l for l in lines if l["kind"] == "chat"][-1]
    assert chat_line["status"] == 200
    assert chat_line["user_id"] == a.user_id and chat_line["workspace_id"] == a.workspace_id
    assert chat_line["request_id"] == r.headers["x-request-id"]
    assert chat_line["path"] == "/workspaces/{workspace_id}/chat"  # the pattern, not real ids
    assert chat_line["input_tokens"] == 120 and chat_line["output_tokens"] == 30
    assert {"rewrite", "search", "first_token", "answer"} <= set(chat_line["steps_ms"])
    assert any(l["kind"] == "ingest" for l in lines)  # the background reading was logged too


def test_errors_are_logged_with_their_status(client, new_user, capsys):
    a = new_user("a")
    capsys.readouterr()
    assert client.get(f"/workspaces/{a.workspace_id}/documents/99999999", headers=a.headers).status_code == 404
    lines = [l for l in json_lines(capsys.readouterr().out) if l["event"] == "request_finished"]
    assert lines[-1]["status"] == 404
    assert lines[-1]["path"] == "/workspaces/{workspace_id}/documents/{document_id}"


def test_health_checks_are_not_logged(client, capsys):
    capsys.readouterr()
    client.get("/health")
    assert "request_finished" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Tokens and cost
# ---------------------------------------------------------------------------
def test_cost_numbers():
    assert cost_usd("gpt-4o-mini", 1_000_000, 1_000_000) == pytest.approx(0.75)
    assert cost_usd("gpt-4o-mini", 120, 30) == pytest.approx(0.000036)
    assert cost_usd("text-embedding-3-small", 1_000_000) == pytest.approx(0.02)
    assert cost_usd("some-new-model", 1000, 1000) == 0.0


def test_a_question_is_saved_with_tokens_cost_and_step_times(client, new_user, upload, monkeypatch):
    import chat

    a = new_user("a")
    upload(a, a.workspace_id, "menu.txt", "Coffee costs 40 pesos.")
    monkeypatch.setattr(chat, "client", FakeOpenAI("It costs 40 (menu.txt).", 120, 30))
    ask(client, a)

    row = usage_rows(a.workspace_id, "chat")[-1]
    assert row.user_id == a.user_id and row.status == 200
    assert (row.input_tokens, row.output_tokens) == (120, 30)
    assert row.cost_usd == pytest.approx(0.000036)
    assert row.duration_ms >= 0
    assert {"rewrite", "search", "first_token", "answer"} <= set(row.details["steps_ms"])


def test_blocked_questions_are_saved_with_their_status(client, new_user, monkeypatch):
    import limiter

    monkeypatch.setenv("RATE_LIMITS", "on")
    monkeypatch.setitem(limiter.LIMITS, "chat", (0, 60))
    a = new_user("a")
    r = client.post(f"/workspaces/{a.workspace_id}/chat", headers=a.headers, json={"question": "hi"})
    assert r.status_code == 429
    assert usage_rows(a.workspace_id, "chat")[-1].status == 429


def test_embedding_tokens_are_counted_for_reading_and_for_search(client, new_user, upload, real_embeddings):
    a = new_user("a")
    upload(a, a.workspace_id, "notes.txt", "some notes about okapis")
    ingest_row = usage_rows(a.workspace_id, "ingest")[-1]
    assert ingest_row.embed_tokens == 1000
    assert ingest_row.cost_usd == pytest.approx(0.00002)
    assert ingest_row.workspace_id == a.workspace_id and ingest_row.user_id == a.user_id

    client.post(f"/workspaces/{a.workspace_id}/search", headers=a.headers, json={"query": "okapis"})
    assert usage_rows(a.workspace_id, "search")[-1].embed_tokens == 1000


def test_the_agents_search_tool_is_counted_for_the_right_workspace(client, new_user, upload, real_embeddings):
    a = new_user("a")
    upload(a, a.workspace_id, "notes.txt", "some notes about okapis")
    call_tool(client, create_mcp_token(a.user_id, a.workspace_id), "search_documents", {"query": "okapis"})

    row = usage_rows(a.workspace_id, "tool")[-1]
    assert row.user_id == a.user_id and row.embed_tokens == 1000


def test_a_failure_to_save_numbers_never_breaks_the_request(client, new_user, monkeypatch, capsys):
    import chat
    import metrics

    a = new_user("a")
    monkeypatch.setattr(chat, "client", FakeOpenAI("hello"))

    def broken(*args, **kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(metrics, "_insert_usage", broken)
    capsys.readouterr()
    ask(client, a)  # still a normal 200
    assert "usage_save_failed" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The usage page
# ---------------------------------------------------------------------------
def test_usage_page_adds_up_and_stays_inside_the_workspace(client, new_user, upload, monkeypatch):
    import chat

    a, b = new_user("a"), new_user("b")
    monkeypatch.setattr(chat, "client", FakeOpenAI("ok", 100, 20))
    for _ in range(3):
        ask(client, a)
    ask(client, b)  # someone else's usage must not show up for a

    stats = client.get(f"/workspaces/{a.workspace_id}/usage?days=7", headers=a.headers).json()
    chat_stats = [k for k in stats["by_kind"] if k["kind"] == "chat"][0]
    assert chat_stats["requests"] == 3 and chat_stats["errors"] == 0
    assert chat_stats["input_tokens"] == 300 and chat_stats["output_tokens"] == 60
    assert chat_stats["cost_usd"] == pytest.approx(3 * 0.000027)
    assert chat_stats["avg_ms"] >= 0 and chat_stats["p95_ms"] >= 0
    assert stats["total"]["requests"] == 3
    assert stats["total"]["cost_usd"] == pytest.approx(3 * 0.000027)
    assert sum(d["requests"] for d in stats["by_day"]) == 3


def test_an_empty_workspace_shows_zeros(client, new_user):
    a = new_user("a")
    stats = client.get(f"/workspaces/{a.workspace_id}/usage", headers=a.headers).json()
    assert stats["total"] == {"requests": 0, "errors": 0, "tokens": 0, "cost_usd": 0}
    assert stats["by_kind"] == [] and stats["by_day"] == []


def test_only_owners_can_open_the_usage_page(client, new_user):
    owner, member, viewer, outsider = new_user("o"), new_user("m"), new_user("v"), new_user("x")
    for who, role in ((member, "member"), (viewer, "viewer")):
        client.post(f"/workspaces/{owner.workspace_id}/members", headers=owner.headers, json={"email": who.email, "role": role})
    url = f"/workspaces/{owner.workspace_id}/usage"
    assert client.get(url, headers=owner.headers).status_code == 200
    for who in (member, viewer, outsider):
        assert client.get(url, headers=who.headers).status_code == 403


def test_the_days_option_is_kept_in_range(client, new_user):
    a = new_user("a")
    assert client.get(f"/workspaces/{a.workspace_id}/usage?days=100000", headers=a.headers).json()["days"] == 90
    assert client.get(f"/workspaces/{a.workspace_id}/usage?days=0", headers=a.headers).json()["days"] == 1


def test_tool_calls_are_linked_to_the_question_that_made_them(client, new_user, upload, real_embeddings, capsys):
    a = new_user("a")
    upload(a, a.workspace_id, "notes.txt", "some notes about okapis")
    capsys.readouterr()

    r = client.post(
        "/mcp/",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {create_mcp_token(a.user_id, a.workspace_id)}",
            "X-Parent-Request-ID": "abc123def456",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_documents", "arguments": {}}},
    )
    assert r.status_code == 200
    lines = [l for l in json_lines(capsys.readouterr().out) if l["event"] == "request_finished" and l["kind"] == "tool"]
    assert lines[-1]["parent_request_id"] == "abc123def456"
    assert lines[-1]["request_id"] != "abc123def456"  # the tool call still has its own id