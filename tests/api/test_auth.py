PREFIX = "/api/v1"


async def test_register_returns_201(client):
    resp = await client.post(
        f"{PREFIX}/auth/register",
        json={"email": "new@example.com", "password": "test123456", "display_name": "New"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new@example.com"
    assert "hashed_password" not in body


async def test_register_duplicate_email_returns_409(client):
    payload = {"email": "dup@example.com", "password": "test123456"}
    resp1 = await client.post(f"{PREFIX}/auth/register", json=payload)
    assert resp1.status_code == 201
    resp2 = await client.post(f"{PREFIX}/auth/register", json=payload)
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "conflict"


async def test_register_invalid_email_returns_422_unified_format(client):
    resp = await client.post(
        f"{PREFIX}/auth/register", json={"email": "not-an-email", "password": "test123456"}
    )
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "validation_error"
    assert "request_id" in error


async def test_login_success_and_me(client):
    await client.post(f"{PREFIX}/auth/register", json={"email": "u@example.com", "password": "test123456"})
    resp = await client.post(f"{PREFIX}/auth/login", json={"email": "u@example.com", "password": "test123456"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    me = await client.get(f"{PREFIX}/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "u@example.com"


async def test_login_wrong_password_returns_401(client):
    await client.post(f"{PREFIX}/auth/register", json={"email": "u2@example.com", "password": "test123456"})
    resp = await client.post(f"{PREFIX}/auth/login", json={"email": "u2@example.com", "password": "wrong456"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_me_without_token_returns_401(client):
    resp = await client.get(f"{PREFIX}/users/me")
    assert resp.status_code == 401


async def test_me_with_invalid_token_returns_401(client):
    resp = await client.get(f"{PREFIX}/users/me", headers={"Authorization": "Bearer invalid-token"})
    assert resp.status_code == 401
