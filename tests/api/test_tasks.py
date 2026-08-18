PREFIX = "/api/v1"


async def _create_task(client, headers, payload=None, idem_key=None, task_type="echo"):
    h = dict(headers)
    if idem_key:
        h["Idempotency-Key"] = idem_key
    return await client.post(
        f"{PREFIX}/tasks",
        json={"type": task_type, "payload": payload or {"ping": "pong"}},
        headers=h,
    )


async def test_create_task_returns_202_and_publishes(client, auth_headers, fake_publisher):
    resp = await _create_task(client, auth_headers)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert body["type"] == "echo"
    assert fake_publisher.published == [{"task_id": body["id"], "task_type": "echo"}]


async def test_create_task_invalid_type_rejected(client, auth_headers):
    resp = await client.post(
        f"{PREFIX}/tasks",
        json={"type": "unknown", "payload": {"x": 1}},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_idempotency_key_returns_same_task(client, auth_headers):
    resp1 = await _create_task(client, auth_headers, idem_key="key-1")
    resp2 = await _create_task(client, auth_headers, idem_key="key-1")
    assert resp1.json()["id"] == resp2.json()["id"]


async def test_task_lifecycle_succeeded(client, auth_headers, fake_redis):
    from app.mq.consumer import handle_task

    resp = await _create_task(client, auth_headers)
    task_id = resp.json()["id"]

    await handle_task(task_id, redis=fake_redis)

    resp = await client.get(f"{PREFIX}/tasks/{task_id}", headers=auth_headers)
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["result"] == {"echo": {"ping": "pong"}}
    assert body["started_at"] is not None
    assert body["finished_at"] is not None

    snapshot = await fake_redis.hgetall(f"task:{task_id}")
    assert snapshot["status"] == "succeeded"


async def test_task_retry_then_fail(client, auth_headers, fake_redis):
    """summarize 缺少 text：前两次重试回 pending，第三次标记 failed。"""
    from app.core.config import settings
    from app.mq.consumer import handle_task

    resp = await _create_task(client, auth_headers, payload={"no_text": True}, task_type="summarize")
    task_id = resp.json()["id"]

    for i in range(settings.task_max_retries - 1):
        await handle_task(task_id, redis=fake_redis)
        resp = await client.get(f"{PREFIX}/tasks/{task_id}", headers=auth_headers)
        assert resp.json()["status"] == "pending", f"第 {i + 1} 次应回到 pending"
        assert resp.json()["retry_count"] == i + 1

    await handle_task(task_id, redis=fake_redis)
    resp = await client.get(f"{PREFIX}/tasks/{task_id}", headers=auth_headers)
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error"]["message"]


async def test_handle_task_idempotent_double_execution(client, auth_headers, fake_redis):
    from app.mq.consumer import handle_task

    resp = await _create_task(client, auth_headers)
    task_id = resp.json()["id"]
    await handle_task(task_id, redis=fake_redis)
    await handle_task(task_id, redis=fake_redis)  # 重复消费应被 CAS 拦截

    resp = await client.get(f"{PREFIX}/tasks/{task_id}", headers=auth_headers)
    assert resp.json()["status"] == "succeeded"
    assert resp.json()["retry_count"] == 0


async def test_cancel_pending_task(client, auth_headers):
    resp = await _create_task(client, auth_headers)
    task_id = resp.json()["id"]

    resp = await client.post(f"{PREFIX}/tasks/{task_id}/cancel", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    resp = await client.post(f"{PREFIX}/tasks/{task_id}/cancel", headers=auth_headers)
    assert resp.status_code == 409


async def test_task_list_and_filter(client, auth_headers):
    await _create_task(client, auth_headers)
    await _create_task(client, auth_headers, task_type="summarize", payload={"text": "abc"})

    resp = await client.get(f"{PREFIX}/tasks", headers=auth_headers)
    assert resp.json()["total"] == 2

    resp = await client.get(f"{PREFIX}/tasks?status=pending", headers=auth_headers)
    assert resp.json()["total"] == 2


async def test_task_isolated_between_users(client, auth_headers):
    resp = await _create_task(client, auth_headers)
    task_id = resp.json()["id"]

    await client.post(
        f"{PREFIX}/auth/register", json={"email": "o@example.com", "password": "demo123456"}
    )
    login = await client.post(
        f"{PREFIX}/auth/login", json={"email": "o@example.com", "password": "demo123456"}
    )
    other = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get(f"{PREFIX}/tasks/{task_id}", headers=other)
    assert resp.status_code == 404


async def test_task_status_snapshot_endpoint(client, auth_headers, fake_redis):
    resp = await _create_task(client, auth_headers)
    task_id = resp.json()["id"]
    resp = await client.get(f"{PREFIX}/tasks/{task_id}/status", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["snapshot"]["status"] == "pending"


async def test_cancel_task_syncs_redis_snapshot(client, auth_headers, fake_redis):
    """取消任务后 Redis 快照必须同步为 cancelled，否则轮询读到过期 pending。"""
    resp = await _create_task(client, auth_headers)
    task_id = resp.json()["id"]

    resp = await client.post(f"{PREFIX}/tasks/{task_id}/cancel", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    snapshot = await fake_redis.hgetall(f"task:{task_id}")
    assert snapshot["status"] == "cancelled"

    resp = await client.get(f"{PREFIX}/tasks/{task_id}/status", headers=auth_headers)
    assert resp.json()["snapshot"]["status"] == "cancelled"


async def test_reap_stale_running_task_resets_to_pending(client, auth_headers, fake_redis):
    """补偿扫描：worker 崩溃后卡在 running 的任务应复位回 pending 以便重新认领。"""
    from datetime import UTC, datetime, timedelta

    from app.db.session import db
    from app.mq.consumer import claim_task
    from app.services.task_service import reap_stale_tasks

    resp = await _create_task(client, auth_headers)
    task_id = resp.json()["id"]

    assert db.session_factory is not None
    # 模拟 worker 认领后崩溃：任务变为 running，且 started_at 已过期
    async with db.session_factory() as session:
        assert await claim_task(session, task_id)

    from app.models.task import Task

    async with db.session_factory() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        task.started_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()

    async with db.session_factory() as session:
        count = await reap_stale_tasks(session, redis=fake_redis, stale_seconds=60)
        assert count == 1

    async with db.session_factory() as session:
        task = await session.get(Task, task_id)
        assert task.status == "pending"
        assert task.started_at is None

    snapshot = await fake_redis.hgetall(f"task:{task_id}")
    assert snapshot["status"] == "pending"


async def test_finalize_task_discards_stale_worker_result_after_reclaim(client, auth_headers, fake_redis):
    """reaper/CAS 边界：任务被复位并被新 worker 认领后，旧 worker 的 CAS 写回必须被丢弃。"""
    from sqlalchemy import update

    from app.db.session import db
    from app.models.task import Task
    from app.mq.consumer import claim_task
    from app.services.task_service import finalize_task

    resp = await _create_task(client, auth_headers)
    task_id = resp.json()["id"]
    assert db.session_factory is not None

    # worker A 认领，记录 claimed_at
    async with db.session_factory() as session:
        assert await claim_task(session, task_id)
    async with db.session_factory() as session:
        claimed_at_a = (await session.get(Task, task_id)).started_at

    # 模拟 reaper 复位 + worker B 认领（started_at 变化）
    async with db.session_factory() as session:
        await session.execute(
            update(Task).where(Task.id == task_id).values(status="pending", started_at=None)
        )
        await session.commit()
    async with db.session_factory() as session:
        assert await claim_task(session, task_id)

    # worker A 用旧 claimed_at 写回 → 被拒绝，且不得污染 DB
    async with db.session_factory() as session:
        owned = await finalize_task(session, task_id, claimed_at_a, "succeeded", {"summary": "old"}, None, 0)
    assert owned is False
    async with db.session_factory() as session:
        task = await session.get(Task, task_id)
        assert task.status == "running"
        assert task.result is None

    # worker B 用新 claimed_at 正常写回
    async with db.session_factory() as session:
        claimed_at_b = (await session.get(Task, task_id)).started_at
    async with db.session_factory() as session:
        assert await finalize_task(session, task_id, claimed_at_b, "succeeded", {"summary": "new"}, None, 0)
    async with db.session_factory() as session:
        task = await session.get(Task, task_id)
        assert task.status == "succeeded"
        assert task.result == {"summary": "new"}
