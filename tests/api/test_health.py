PREFIX = "/api/v1"


async def test_healthz(client):
    resp = await client.get(f"{PREFIX}/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz_checks_dependencies(client):
    resp = await client.get(f"{PREFIX}/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["checks"]["postgres"] is True
    assert body["checks"]["redis"] is True
    assert body["checks"]["rabbitmq"] is True  # FakePublisher.is_ready


async def test_request_id_header_returned(client):
    resp = await client.get(f"{PREFIX}/healthz", headers={"X-Request-ID": "rid-123"})
    assert resp.headers["X-Request-ID"] == "rid-123"
