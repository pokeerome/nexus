import uuid


def add_member(client, owner, user, role):
    return client.post(
        f"/workspaces/{owner.workspace_id}/members",
        headers=owner.headers,
        json={"email": user.email, "role": role},
    )


def test_viewer_can_read_and_search_but_not_change_anything(client, new_user, upload):
    owner, viewer = new_user("owner"), new_user("viewer")
    assert add_member(client, owner, viewer, "viewer").status_code == 200
    ws = owner.workspace_id
    marker = f"tapir{uuid.uuid4().hex}"
    doc = upload(owner, ws, "shared.txt", f"shared {marker}").json()

    assert client.get(f"/workspaces/{ws}/documents", headers=viewer.headers).status_code == 200
    r = client.post(f"/workspaces/{ws}/search", headers=viewer.headers, json={"query": marker})
    assert r.status_code == 200 and r.json()

    assert upload(viewer, ws, "nope.txt", "x").status_code == 403
    assert client.delete(f"/workspaces/{ws}/documents/{doc['id']}", headers=viewer.headers).status_code == 403


def test_member_can_upload_and_remove_own_files_only(client, new_user, upload):
    owner, member = new_user("owner"), new_user("member")
    add_member(client, owner, member, "member")
    ws = owner.workspace_id

    owners_doc = upload(owner, ws, "owners.txt", "owner file").json()
    members_doc = upload(member, ws, "members.txt", "member file").json()
    assert members_doc["status"] == "ready"

    assert client.delete(f"/workspaces/{ws}/documents/{owners_doc['id']}", headers=member.headers).status_code == 403
    assert client.delete(f"/workspaces/{ws}/documents/{members_doc['id']}", headers=member.headers).status_code == 200


def test_owner_can_remove_anyones_file(client, new_user, upload):
    owner, member = new_user("owner"), new_user("member")
    add_member(client, owner, member, "member")
    ws = owner.workspace_id
    doc = upload(member, ws, "members.txt", "member file").json()
    assert client.delete(f"/workspaces/{ws}/documents/{doc['id']}", headers=owner.headers).status_code == 200


def test_only_owners_manage_members(client, new_user):
    owner, member, viewer, newcomer = new_user("owner"), new_user("member"), new_user("viewer"), new_user("newcomer")
    add_member(client, owner, member, "member")
    add_member(client, owner, viewer, "viewer")
    ws = owner.workspace_id

    for who in (member, viewer):
        assert client.post(f"/workspaces/{ws}/members", headers=who.headers, json={"email": newcomer.email, "role": "member"}).status_code == 403
        assert client.patch(f"/workspaces/{ws}/members/{viewer.user_id}", headers=who.headers, json={"role": "owner"}).status_code == 403
        assert client.delete(f"/workspaces/{ws}/members/{owner.user_id}", headers=who.headers).status_code == 403


def test_member_list_is_visible_to_all_members(client, new_user):
    owner, viewer = new_user("owner"), new_user("viewer")
    add_member(client, owner, viewer, "viewer")
    r = client.get(f"/workspaces/{owner.workspace_id}/members", headers=viewer.headers)
    assert r.status_code == 200
    roles = {m["email"]: m["role"] for m in r.json()}
    assert roles == {owner.email: "owner", viewer.email: "viewer"}


def test_adding_members_checks_the_email(client, new_user):
    owner, other = new_user("owner"), new_user("other")
    ws = owner.workspace_id
    assert client.post(f"/workspaces/{ws}/members", headers=owner.headers, json={"email": "nobody@example.com", "role": "member"}).status_code == 404
    assert add_member(client, owner, other, "member").status_code == 200
    assert add_member(client, owner, other, "member").status_code == 400  # already a member


def test_new_member_sees_the_workspace_with_their_role(client, new_user):
    owner, other = new_user("owner"), new_user("other")
    add_member(client, owner, other, "viewer")
    me = client.get("/auth/me", headers=other.headers).json()
    roles = {w["id"]: w["role"] for w in me["workspaces"]}
    assert roles[owner.workspace_id] == "viewer"
    assert roles[other.workspace_id] == "owner"  # their own workspace is untouched


def test_a_workspace_always_keeps_one_owner(client, new_user):
    owner, other = new_user("owner"), new_user("other")
    ws = owner.workspace_id
    add_member(client, owner, other, "member")

    # the only owner cannot demote or remove themselves
    assert client.patch(f"/workspaces/{ws}/members/{owner.user_id}", headers=owner.headers, json={"role": "member"}).status_code == 400
    assert client.delete(f"/workspaces/{ws}/members/{owner.user_id}", headers=owner.headers).status_code == 400

    # after promoting a second owner, it is allowed
    assert client.patch(f"/workspaces/{ws}/members/{other.user_id}", headers=owner.headers, json={"role": "owner"}).status_code == 200
    assert client.patch(f"/workspaces/{ws}/members/{owner.user_id}", headers=owner.headers, json={"role": "member"}).status_code == 200


def test_a_member_can_leave_but_not_remove_others(client, new_user):
    owner, member, viewer = new_user("owner"), new_user("member"), new_user("viewer")
    add_member(client, owner, member, "member")
    add_member(client, owner, viewer, "viewer")
    ws = owner.workspace_id

    assert client.delete(f"/workspaces/{ws}/members/{viewer.user_id}", headers=member.headers).status_code == 403
    assert client.delete(f"/workspaces/{ws}/members/{member.user_id}", headers=member.headers).status_code == 200
    assert client.get(f"/workspaces/{ws}/documents", headers=member.headers).status_code == 403  # access is gone


def test_removed_member_loses_access_to_files_and_search(client, new_user, upload):
    owner, member = new_user("owner"), new_user("member")
    add_member(client, owner, member, "member")
    ws = owner.workspace_id
    upload(owner, ws, "x.txt", "hello")
    assert client.get(f"/workspaces/{ws}/documents", headers=member.headers).status_code == 200

    client.delete(f"/workspaces/{ws}/members/{member.user_id}", headers=owner.headers)
    assert client.get(f"/workspaces/{ws}/documents", headers=member.headers).status_code == 403
    assert client.post(f"/workspaces/{ws}/search", headers=member.headers, json={"query": "hello"}).status_code == 403


def test_documents_show_who_uploaded_them(client, new_user, upload):
    owner, member = new_user("owner"), new_user("member")
    add_member(client, owner, member, "member")
    ws = owner.workspace_id
    doc = upload(member, ws, "members.txt", "member file").json()
    assert doc["uploaded_by"] == member.user_id
    listed = client.get(f"/workspaces/{ws}/documents", headers=owner.headers).json()
    assert listed[0]["uploaded_by"] == member.user_id