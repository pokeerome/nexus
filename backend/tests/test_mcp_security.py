import uuid
from datetime import datetime, timedelta, timezone

import jwt

from security import ALGORITHM, SECRET_KEY, create_access_token, create_mcp_token

MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def call_tool(client, token, name, arguments=None):
    headers = dict(MCP_HEADERS)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    r = client.post(
        "/mcp/",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}},
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    text = " ".join(block.get("text", "") for block in result["content"])
    return result["isError"], text


def test_each_token_sees_only_its_own_workspace(client, new_user, upload):
    a, b = new_user("a"), new_user("b")
    upload(a, a.workspace_id, f"only_a_{uuid.uuid4().hex[:6]}.txt", "A file")
    upload(b, b.workspace_id, f"only_b_{uuid.uuid4().hex[:6]}.txt", "B file")

    error, text_a = call_tool(client, create_mcp_token(a.user_id, a.workspace_id), "list_documents")
    assert not error and "only_a_" in text_a and "only_b_" not in text_a

    error, text_b = call_tool(client, create_mcp_token(b.user_id, b.workspace_id), "list_documents")
    assert not error and "only_b_" in text_b and "only_a_" not in text_b


def test_the_ai_cannot_pick_another_workspace(client, new_user, upload):
    a, b = new_user("a"), new_user("b")
    upload(b, b.workspace_id, f"only_b_{uuid.uuid4().hex[:6]}.txt", "B file")
    token_a = create_mcp_token(a.user_id, a.workspace_id)

    # Even if the AI tries to sneak in a workspace id, the token decides
    _, text = call_tool(client, token_a, "list_documents", {"workspace_id": b.workspace_id})
    assert "only_b_" not in text
    _, text = call_tool(client, token_a, "search_documents", {"query": "B file", "workspace_id": b.workspace_id})
    assert "only_b_" not in text


def test_mcp_search_is_limited_to_the_token_workspace(client, new_user, upload):
    a, b = new_user("a"), new_user("b")
    marker = f"narwhal{uuid.uuid4().hex}"
    upload(b, b.workspace_id, "b_only.txt", f"private to B {marker}")
    error, text = call_tool(client, create_mcp_token(a.user_id, a.workspace_id), "search_documents", {"query": marker})
    assert marker not in text and "b_only.txt" not in text


def test_missing_token_is_an_error(client):
    error, text = call_tool(client, None, "list_documents")
    assert error and "Missing token" in text


def test_login_token_does_not_work_as_mcp_token(client, new_user):
    a = new_user("a")
    error, text = call_tool(client, create_access_token(a.user_id), "list_documents")
    assert error


def test_expired_token_is_an_error(client, new_user):
    a = new_user("a")
    expired = jwt.encode(
        {"sub": str(a.user_id), "ws": a.workspace_id, "typ": "mcp", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    error, text = call_tool(client, expired, "list_documents")
    assert error and "expired" in text.lower()


def test_forged_token_is_an_error(client, new_user):
    a = new_user("a")
    forged = jwt.encode(
        {"sub": str(a.user_id), "ws": a.workspace_id, "typ": "mcp", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "a-different-secret-key-used-by-an-attacker",
        algorithm=ALGORITHM,
    )
    error, text = call_tool(client, forged, "list_documents")
    assert error
