import os
import time
import uuid

import pytest

import limiter as limiter_module
from limiter import RateLimiter


# ---------------------------------------------------------------------------
# The counter itself. Runs in memory always, and on Redis too when one is running.
# ---------------------------------------------------------------------------
@pytest.fixture(params=["memory", "redis"])
def rl(request):
    if request.param == "memory":
        return RateLimiter()
    url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
    counter = RateLimiter(url)
    if counter._redis is None:
        pytest.skip("no Redis running here")
    return counter


@pytest.fixture
def key():
    return f"test:{uuid.uuid4().hex}"


def test_allows_up_to_the_limit_then_blocks(rl, key):
    results = [rl.hit(key, 3, 60)[0] for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_blocked_answer_says_how_long_to_wait(rl, key):
    for _ in range(2):
        rl.hit(key, 2, 60)
    allowed, retry_after = rl.hit(key, 2, 60)
    assert not allowed and 1 <= retry_after <= 60


def test_different_keys_do_not_affect_each_other(rl, key):
    other = key + "-other"
    for _ in range(3):
        rl.hit(key, 1, 60)
    assert rl.hit(other, 1, 60)[0] is True


def test_the_window_resets(rl, key):
    assert rl.hit(key, 1, 1)[0] is True
    assert rl.hit(key, 1, 1)[0] is False
    time.sleep(1.2)
    assert rl.hit(key, 1, 1)[0] is True


def test_count_does_not_count_and_reset_clears(rl, key):
    rl.hit(key, 5, 60)
    rl.hit(key, 5, 60)
    assert rl.count(key)[0] == 2
    assert rl.count(key)[0] == 2  # looking twice changes nothing
    rl.reset(key)
    assert rl.count(key)[0] == 0


def test_a_redis_key_without_expiry_gets_one(key):
    url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
    counter = RateLimiter(url)
    if counter._redis is None:
        pytest.skip("no Redis running here")
    counter._redis.set(f"rl:{key}", 5)  # simulates a crash that left no expiry
    counter.hit(key, 100, 30)
    assert 0 < counter._redis.ttl(f"rl:{key}") <= 30


def test_if_redis_fails_it_falls_back_to_memory(key):
    counter = RateLimiter()

    class Broken:
        def pipeline(self):
            raise ConnectionError("down")

        def delete(self, *a):
            raise ConnectionError("down")

    counter._redis = Broken()
    assert [counter.hit(key, 2, 60)[0] for _ in range(3)] == [True, True, False]


# ---------------------------------------------------------------------------
# The limits on the real endpoints
# ---------------------------------------------------------------------------
@pytest.fixture
def limits_on(monkeypatch):
    monkeypatch.setenv("RATE_LIMITS", "on")

    def set_limit(name, limit, window=60):
        monkeypatch.setitem(limiter_module.LIMITS, name, (limit, window))

    return set_limit


def search(client, user, query="hello"):
    return client.post(
        f"/workspaces/{user.workspace_id}/search", headers=user.headers, json={"query": query}
    )


def test_search_is_limited_per_user_and_says_when_to_retry(client, new_user, limits_on):
    limits_on("search", 3)
    a, b = new_user("a"), new_user("b")

    assert [search(client, a).status_code for _ in range(3)] == [200, 200, 200]
    blocked = search(client, a)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert "try again" in blocked.json()["detail"].lower()

    # another user is not affected
    assert search(client, b).status_code == 200


def test_limits_can_be_turned_off(client, new_user, monkeypatch):
    monkeypatch.setitem(limiter_module.LIMITS, "search", (1, 60))
    monkeypatch.setenv("RATE_LIMITS", "off")
    a = new_user("a")
    assert all(search(client, a).status_code == 200 for _ in range(4))


def test_upload_is_limited(client, new_user, upload, limits_on):
    limits_on("upload", 2)
    a = new_user("a")
    codes = [upload(a, a.workspace_id, f"f{i}.txt", "hello").status_code for i in range(3)]
    assert codes == [200, 200, 429]


def test_chat_and_agent_are_limited_before_any_ai_call(client, new_user, limits_on):
    limits_on("chat", 0)  # 0 = the very first request is already too many
    limits_on("agent", 0)
    a = new_user("a")
    r = client.post(f"/workspaces/{a.workspace_id}/chat", headers=a.headers, json={"question": "hi"})
    assert r.status_code == 429
    r = client.post(f"/workspaces/{a.workspace_id}/agent", headers=a.headers, json={"question": "hi"})
    assert r.status_code == 429


def test_the_global_ai_budget_blocks_everyone(client, new_user, limits_on):
    limits_on("llm_global", 0)
    a = new_user("a")
    r = client.post(f"/workspaces/{a.workspace_id}/chat", headers=a.headers, json={"question": "hi"})
    assert r.status_code == 429
    limiter_module.limiter.reset("llm_global:all")


def test_outsiders_get_403_not_429(client, new_user, limits_on):
    limits_on("search", 0)
    owner, outsider = new_user("owner"), new_user("outsider")
    r = client.post(f"/workspaces/{owner.workspace_id}/search", headers=outsider.headers, json={"query": "x"})
    assert r.status_code == 403


def test_adding_members_is_limited(client, new_user, limits_on):
    limits_on("members", 2)
    owner = new_user("owner")
    codes = [
        client.post(
            f"/workspaces/{owner.workspace_id}/members",
            headers=owner.headers,
            json={"email": f"nobody{i}@example.com", "role": "member"},
        ).status_code
        for i in range(3)
    ]
    assert codes == [404, 404, 429]  # 404 = no such user, so the guesses are slowed down


def test_signups_have_a_global_cap(client, limits_on):
    limits_on("signup_global", 2)
    limiter_module.limiter.reset("signup_global:all")
    codes = [
        client.post(
            "/auth/signup",
            json={"email": f"cap-{uuid.uuid4().hex[:8]}@example.com", "password": "password123", "workspace_name": "x"},
        ).status_code
        for _ in range(3)
    ]
    limiter_module.limiter.reset("signup_global:all")
    assert codes == [200, 200, 429]


# ---------------------------------------------------------------------------
# Wrong passwords
# ---------------------------------------------------------------------------
def login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_five_wrong_passwords_lock_that_email_for_a_while(client, new_user, limits_on):
    a, b = new_user("a"), new_user("b")

    assert [login(client, a.email, "wrong-password").status_code for _ in range(5)] == [401] * 5
    locked = login(client, a.email, "password123")  # even the right password waits now
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) >= 1

    assert login(client, b.email, "password123").status_code == 200  # other emails are fine


def test_a_good_login_clears_earlier_mistakes(client, new_user, limits_on):
    a = new_user("a")
    for _ in range(3):
        assert login(client, a.email, "wrong-password").status_code == 401
    assert login(client, a.email, "password123").status_code == 200
    for _ in range(3):
        assert login(client, a.email, "wrong-password").status_code == 401  # not locked: counter started over


def test_email_case_does_not_help_an_attacker(client, new_user, limits_on):
    a = new_user("a")
    for variant in (a.email, a.email.upper(), a.email.title(), a.email, a.email.upper()):
        login(client, variant, "wrong-password")
    assert login(client, a.email, "password123").status_code == 429