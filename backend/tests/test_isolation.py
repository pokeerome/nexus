import uuid

import pytest


def test_no_token_is_rejected(client):
    assert client.get("/auth/me").status_code in (401, 403)
    assert client.get("/workspaces/1/documents").status_code in (401, 403)


def test_garbage_token_is_rejected(client):
    r = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/workspaces/{ws}/documents", None),
        ("get", "/workspaces/{ws}/members", None),
        ("post", "/workspaces/{ws}/search", {"query": "anything"}),
        ("post", "/workspaces/{ws}/chat", {"question": "anything"}),
        ("post", "/workspaces/{ws}/agent", {"question": "anything"}),
        ("post", "/workspaces/{ws}/members", {"email": "x@example.com", "role": "member"}),
    ],
)
def test_outsider_is_blocked_from_every_workspace_endpoint(client, new_user, method, path, body):
    owner, outsider = new_user("owner"), new_user("outsider")
    url = path.format(ws=owner.workspace_id)
    r = getattr(client, method)(url, headers=outsider.headers, **({"json": body} if body else {}))
    assert r.status_code == 403, f"{method.upper()} {url} returned {r.status_code}"


def test_outsider_cannot_upload(client, new_user, upload):
    owner, outsider = new_user("owner"), new_user("outsider")
    r = upload(outsider, owner.workspace_id, "sneaky.txt", "hello")
    assert r.status_code == 403


def test_document_ids_do_not_work_across_workspaces(client, new_user, upload):
    a, b = new_user("a"), new_user("b")
    doc = upload(a, a.workspace_id, "secret.txt", "company A secret plan").json()

    # B asks for A's document through B's own workspace: must look like it does not exist
    assert client.get(f"/workspaces/{b.workspace_id}/documents/{doc['id']}", headers=b.headers).status_code == 404
    assert client.delete(f"/workspaces/{b.workspace_id}/documents/{doc['id']}", headers=b.headers).status_code == 404
    # ...and through A's workspace, B is simply not allowed
    assert client.delete(f"/workspaces/{a.workspace_id}/documents/{doc['id']}", headers=b.headers).status_code == 403

    # A's document is still there
    names = [d["filename"] for d in client.get(f"/workspaces/{a.workspace_id}/documents", headers=a.headers).json()]
    assert "secret.txt" in names


def test_search_never_returns_another_workspaces_chunks(client, new_user, upload):
    a, b = new_user("a"), new_user("b")
    marker_a, marker_b = f"zebra{uuid.uuid4().hex}", f"giraffe{uuid.uuid4().hex}"
    assert upload(a, a.workspace_id, "a_notes.txt", f"Company A notes {marker_a}").json()["status"] == "ready"
    assert upload(b, b.workspace_id, "b_notes.txt", f"Company B notes {marker_b}").json()["status"] == "ready"

    for query in (marker_b, "Company B notes", "notes"):
        hits = client.post(f"/workspaces/{a.workspace_id}/search", headers=a.headers, json={"query": query, "limit": 8}).json()
        assert all(h["filename"] == "a_notes.txt" for h in hits)
        assert marker_b not in str(hits)

    for query in (marker_a, "Company A notes", "notes"):
        hits = client.post(f"/workspaces/{b.workspace_id}/search", headers=b.headers, json={"query": query, "limit": 8}).json()
        assert all(h["filename"] == "b_notes.txt" for h in hits)
        assert marker_a not in str(hits)


def test_own_search_still_finds_own_files(client, new_user, upload):
    a = new_user("a")
    marker = f"okapi{uuid.uuid4().hex}"
    upload(a, a.workspace_id, "mine.txt", f"my own file {marker}")
    hits = client.post(f"/workspaces/{a.workspace_id}/search", headers=a.headers, json={"query": marker}).json()
    assert hits and hits[0]["filename"] == "mine.txt"


def test_deleting_a_document_removes_its_chunks(client, new_user, upload):
    a = new_user("a")
    marker = f"lemur{uuid.uuid4().hex}"
    doc = upload(a, a.workspace_id, "temp.txt", f"temporary {marker}").json()
    assert client.delete(f"/workspaces/{a.workspace_id}/documents/{doc['id']}", headers=a.headers).status_code == 200
    hits = client.post(f"/workspaces/{a.workspace_id}/search", headers=a.headers, json={"query": marker}).json()
    assert marker not in str(hits)


def test_mcp_token_cannot_be_used_to_log_in(client, new_user):
    from security import create_mcp_token

    a = new_user("a")
    token = create_mcp_token(a.user_id, a.workspace_id)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
