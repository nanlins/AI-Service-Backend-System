import pytest

from app.api.v1 import auth as auth_api
from app.api.v1 import messages as messages_api
from app.core.ratelimit import ip_rate_limit, user_rate_limit

PREFIX = "/api/v1"


@pytest.fixture
def tiny_limits(app):
    """把限流依赖替换为极小阈值，方便触发 429。"""
    app.dependency_overrides[auth_api._register_limiter] = ip_rate_limit("auth_register", 2, 60)
    app.dependency_overrides[auth_api._login_limiter] = ip_rate_limit("auth_login", 2, 60)
    app.dependency_overrides[messages_api._message_limiter] = user_rate_limit("message", 2, 60)
    yield
    app.dependency_overrides.clear()


async def test_register_rate_limited_with_retry_after(client, tiny_limits):
    for i in range(2):
        resp = await client.post(
            f"{PREFIX}/auth/register",
            json={"email": f"rl{i}@example.com", "password": "demo123456"},
        )
        assert resp.status_code == 201
    resp = await client.post(
        f"{PREFIX}/auth/register",
        json={"email": "rl2@example.com", "password": "demo123456"},
    )
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"
    assert resp.headers.get("Retry-After") is not None


async def test_login_rate_limited(client, tiny_limits, auth_headers):
    # auth_headers 夹具已产生 1 次 login 计数；限流=2，因此再放行 1 次、之后 429
    resp = await client.post(
        f"{PREFIX}/auth/login",
        json={"email": "tester@example.com", "password": "demo123456"},
    )
    assert resp.status_code == 200
    resp = await client.post(
        f"{PREFIX}/auth/login",
        json={"email": "tester@example.com", "password": "demo123456"},
    )
    assert resp.status_code == 429


async def test_message_rate_limited(client, tiny_limits, auth_headers):
    resp = await client.post(f"{PREFIX}/sessions", json={}, headers=auth_headers)
    session_id = resp.json()["id"]
    for _ in range(2):
        resp = await client.post(
            f"{PREFIX}/sessions/{session_id}/messages",
            json={"content": "hi"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
    resp = await client.post(
        f"{PREFIX}/sessions/{session_id}/messages",
        json={"content": "hi again"},
        headers=auth_headers,
    )
    assert resp.status_code == 429
