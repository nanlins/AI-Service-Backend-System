from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.db.session import db, redis_holder
from app.models.task import TASK_FAILED, TASK_PENDING, TASK_RUNNING, TASK_SUCCEEDED, Task
from app.models.user import User
from app.mq.consumer import TaskConsumer, claim_task, handle_task
from app.mq.delayed import enqueue_retry, pop_ready_retries, retry_delay
from app.services.task_service import finalize_task, reap_stale_tasks


async def _ensure_user() -> None:
    assert db.session_factory is not None
    async with db.session_factory() as session:
        if await session.get(User, 1) is None:
            session.add(User(id=1, email="u1@test.com", hashed_password="x", status="active"))
            await session.commit()


async def _insert_task(type: str = "echo", payload=None, status: str = TASK_PENDING) -> Task:
    await _ensure_user()
    assert db.session_factory is not None
    async with db.session_factory() as session:
        task = Task(user_id=1, type=type, payload=payload or {"x": 1}, status=status)
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task


async def _get_task(task_id: int) -> Task:
    assert db.session_factory is not None
    async with db.session_factory() as session:
        return await session.get(Task, task_id)


def test_retry_delay_exponential_backoff():
    assert retry_delay(1) == settings.task_retry_base_delay
    assert retry_delay(2) == settings.task_retry_base_delay * 2
    assert retry_delay(10) == settings.task_retry_max_delay  # 封顶


async def test_claim_task_success_then_double_claim_fails():
    task = await _insert_task()
    assert db.session_factory is not None
    async with db.session_factory() as session:
        assert await claim_task(session, task.id) is True
        assert await claim_task(session, task.id) is False  # 第二次 CAS 失败
    stored = await _get_task(task.id)
    assert stored.status == TASK_RUNNING
    assert stored.started_at is not None


async def test_handle_task_success_path(fake_redis):
    task = await _insert_task()
    await handle_task(task.id, redis=fake_redis)
    stored = await _get_task(task.id)
    assert stored.status == TASK_SUCCEEDED
    assert stored.result == {"echo": {"x": 1}}
    assert await fake_redis.hget(f"task:{task.id}", "status") == TASK_SUCCEEDED


async def test_handle_task_retriable_enqueues_delayed(fake_redis):
    """summarize 缺 text 触发重试：状态回 pending，写入延迟队列而非立即重投。"""
    task = await _insert_task(type="summarize", payload={"no_text": True})
    await handle_task(task.id, redis=fake_redis)
    stored = await _get_task(task.id)
    assert stored.status == TASK_PENDING
    assert stored.retry_count == 1
    score = await fake_redis.zscore("task:retry:delayed", str(task.id))
    assert score is not None and score > 0


async def test_handle_task_retries_exhausted_fails(fake_redis):
    task = await _insert_task(type="summarize", payload={"no_text": True})
    for _ in range(settings.task_max_retries):
        await handle_task(task.id, redis=fake_redis)
    stored = await _get_task(task.id)
    assert stored.status == TASK_FAILED
    assert stored.retry_count == settings.task_max_retries


async def test_enqueue_and_pop_delayed_retries(fake_redis):
    await enqueue_retry(fake_redis, 11, 1)
    await enqueue_retry(fake_redis, 22, 2)
    # 未到期不应弹出
    assert await pop_ready_retries(fake_redis) == []
    # 直接把 score 改到过去再弹出
    await fake_redis.zadd("task:retry:delayed", {"11": 0, "22": 0})
    assert sorted(await pop_ready_retries(fake_redis)) == [11, 22]
    assert await pop_ready_retries(fake_redis) == []


async def test_finalize_task_ownership_cas():
    task = await _insert_task()
    assert db.session_factory is not None
    async with db.session_factory() as session:
        await claim_task(session, task.id)
    claimed_at = (await _get_task(task.id)).started_at
    # 用错误的 claimed_at 写回 → 所有权丢失
    async with db.session_factory() as session:
        owned = await finalize_task(
            session, task.id, datetime.now(UTC), TASK_SUCCEEDED, {"x": 1}, None, 0
        )
        assert owned is False
    stored = await _get_task(task.id)
    assert stored.status == TASK_RUNNING  # 未被覆盖
    # 用正确的 claimed_at 写回 → 成功
    async with db.session_factory() as session:
        owned = await finalize_task(session, task.id, claimed_at, TASK_SUCCEEDED, {"x": 1}, None, 0)
        assert owned is True
    stored = await _get_task(task.id)
    assert stored.status == TASK_SUCCEEDED


async def test_reap_stale_tasks_resets(fake_redis):
    stale = await _insert_task(type="echo", status=TASK_RUNNING)
    assert db.session_factory is not None
    async with db.session_factory() as session:
        stale_db = await session.get(Task, stale.id)
        stale_db.started_at = datetime.now(UTC) - timedelta(seconds=settings.task_reap_stale_seconds + 10)
        await session.commit()
    assert db.session_factory is not None
    async with db.session_factory() as session:
        n = await reap_stale_tasks(session, fake_redis)
    assert n == 1
    stored = await _get_task(stale.id)
    assert stored.status == TASK_PENDING
    assert stored.started_at is None
    assert await fake_redis.hget(f"task:{stale.id}", "status") == TASK_PENDING


async def test_reap_skips_fresh_running():
    fresh = await _insert_task(type="echo", status=TASK_RUNNING)
    assert db.session_factory is not None
    async with db.session_factory() as session:
        n = await reap_stale_tasks(session)
    assert n == 0
    assert (await _get_task(fresh.id)).status == TASK_RUNNING


class _FakeMessage:
    def __init__(self, body: dict) -> None:
        self.body = json.dumps(body).encode()

    @asynccontextmanager
    async def process(self, **kwargs):
        yield


async def test_on_message_acquires_lock_and_processes(fake_redis, monkeypatch):
    task = await _insert_task()
    monkeypatch.setattr(redis_holder, "client", fake_redis)
    consumer = TaskConsumer()
    await consumer._on_message(_FakeMessage({"task_id": task.id}))
    stored = await _get_task(task.id)
    assert stored.status == TASK_SUCCEEDED
    # 锁已被释放
    assert await fake_redis.get(f"lock:task:{task.id}") is None


async def test_on_message_skips_when_lock_held(fake_redis, monkeypatch):
    task = await _insert_task()
    monkeypatch.setattr(redis_holder, "client", fake_redis)
    await fake_redis.set(f"lock:task:{task.id}", "another-worker", nx=True, ex=600)
    consumer = TaskConsumer()
    await consumer._on_message(_FakeMessage({"task_id": task.id}))
    stored = await _get_task(task.id)
    assert stored.status == TASK_PENDING  # 未被执行


async def test_handle_task_retriable_republishes_when_no_redis(fake_publisher):
    """redis 为 None 时（无 Redis 环境），可重试失败应走立即重投。"""
    task = await _insert_task(type="summarize", payload={"no_text": True})
    await handle_task(task.id, redis=None, publisher=fake_publisher)
    stored = await _get_task(task.id)
    assert stored.status == TASK_PENDING
    assert fake_publisher.published == [{"task_id": task.id, "task_type": "summarize"}]


async def test_handle_task_unknown_type_fails(fake_redis):
    task = await _insert_task(type="nope")
    for _ in range(settings.task_max_retries):
        await handle_task(task.id, redis=fake_redis)
    stored = await _get_task(task.id)
    assert stored.status == TASK_FAILED
    assert stored.error is not None
