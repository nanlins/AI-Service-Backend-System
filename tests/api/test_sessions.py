PREFIX = "/api/v1"


async def _register(client, email: str) -> dict[str, str]:
    await client.post(f"{PREFIX}/auth/register", json={"email": email, "password": "demo123456"})
    resp = await client.post(f"{PREFIX}/auth/login", json={"email": email, "password": "demo123456"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_session_crud(client, auth_headers):
    resp = await client.post(
        f"{PREFIX}/sessions",
        json={"title": "测试会话", "system_prompt": "你是测试助手"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    session_id = resp.json()["id"]
    assert resp.json()["title"] == "测试会话"

    resp = await client.get(f"{PREFIX}/sessions", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    resp = await client.get(f"{PREFIX}/sessions/{session_id}", headers=auth_headers)
    assert resp.status_code == 200

    resp = await client.patch(
        f"{PREFIX}/sessions/{session_id}", json={"title": "改名"}, headers=auth_headers
    )
    assert resp.json()["title"] == "改名"

    resp = await client.delete(f"{PREFIX}/sessions/{session_id}", headers=auth_headers)
    assert resp.status_code == 204
    resp = await client.get(f"{PREFIX}/sessions/{session_id}", headers=auth_headers)
    assert resp.status_code == 404


async def test_session_isolated_between_users(client, auth_headers):
    resp = await client.post(f"{PREFIX}/sessions", json={}, headers=auth_headers)
    session_id = resp.json()["id"]

    other_headers = await _register(client, "other@example.com")
    resp = await client.get(f"{PREFIX}/sessions/{session_id}", headers=other_headers)
    assert resp.status_code == 404  # 越权访问返回 404，不泄露存在性


async def test_session_requires_auth(client):
    resp = await client.get(f"{PREFIX}/sessions")
    assert resp.status_code == 401
