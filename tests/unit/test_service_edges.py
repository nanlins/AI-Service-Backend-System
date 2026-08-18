"""服务层边界用例：禁用用户、任务发布失败、DB/Redis 惰性初始化、拓扑声明。"""

import pytest
from sqlalchemy import select

from app.core.deps import get_redis
from app.core.errors import ConflictError, UpstreamError
from app.db.session import db, redis_holder
from app.models.user import User
from app.mq.publisher import publisher_holder
from app.mq.topology import declare_topology
from app.schemas.auth import RegisterIn
from app.schemas.task import TaskCreate
from app.services import task_service, user_service


def _make_register(email: str) -> RegisterIn:
    return RegisterIn(email=email, password="secret123")


async def test_login_disabled_user_rejected(client):
    assert db.session_factory is not None
    async with db.session_factory() as session:
        await user_service.register_user(session, _make_register("disabled@x.com"))
    async with db.session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "disabled@x.com"))
        user.status = "disabled"
        await session.commit()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "disabled@x.com", "password": "secret123"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_register_duplicate_raises_conflict():
    assert db.session_factory is not None
    async with db.session_factory() as session:
        await user_service.register_user(session, _make_register("dup@x.com"))
    async with db.session_factory() as session:
        with pytest.raises(ConflictError):
            await user_service.register_user(session, _make_register("dup@x.com"))


async def test_create_task_publish_failure_raises_upstream(fake_redis):
    class BoomPublisher:
        async def publish_task(self, task_id, task_type):
            raise RuntimeError("mq down")

    assert db.session_factory is not None
    async with db.session_factory() as session:
        user = await user_service.register_user(session, _make_register("task@x.com"))
    async with db.session_factory() as session:
        with pytest.raises(UpstreamError):
            await task_service.create_task(
                session, fake_redis, BoomPublisher(), user.id, TaskCreate(type="echo", payload={"x": 1})
            )


async def test_create_task_idempotency_returns_existing(fake_redis, fake_publisher):
    assert db.session_factory is not None
    async with db.session_factory() as session:
        user = await user_service.register_user(session, _make_register("idem@x.com"))
    async with db.session_factory() as session:
        first = await task_service.create_task(
            session, fake_redis, fake_publisher, user.id, TaskCreate(type="echo", payload={"x": 1}), idempotency_key="k1"
        )
    async with db.session_factory() as session:
        second = await task_service.create_task(
            session, fake_redis, fake_publisher, user.id, TaskCreate(type="echo", payload={"x": 1}), idempotency_key="k1"
        )
    assert first.id == second.id
    assert len(fake_publisher.published) == 1


async def test_cancel_succeeded_task_conflicts(fake_redis, fake_publisher):
    from app.mq.consumer import handle_task

    assert db.session_factory is not None
    async with db.session_factory() as session:
        user = await user_service.register_user(session, _make_register("cancel@x.com"))
        task = await task_service.create_task(
            session, fake_redis, fake_publisher, user.id, TaskCreate(type="echo", payload={"x": 1})
        )
    await handle_task(task.id, redis=fake_redis)
    assert db.session_factory is not None
    async with db.session_factory() as session:
        user = await session.scalar(select(User).where(User.email == "cancel@x.com"))
        with pytest.raises(ConflictError):
            await task_service.cancel_task(session, fake_redis, user.id, task.id)


async def test_db_redis_lazy_init(monkeypatch):
    import fakeredis.aioredis

    monkeypatch.setattr(
        "redis.asyncio.Redis.from_url",
        lambda url, decode_responses=False: fakeredis.aioredis.FakeRedis(decode_responses=decode_responses),
    )
    redis_holder.client = None
    assert get_redis() is not None
    assert redis_holder.ready
    await redis_holder.close()
    assert redis_holder.client is None


async def test_declare_topology_with_fake_channel():
    class FakeQueue:
        async def bind(self, exchange, routing_key=None):
            self._bind = (exchange, routing_key)

    class FakeChannel:
        def __init__(self):
            self.queues = {}
            self.exchanges = {}

        async def declare_exchange(self, name, type_, durable=False):
            self.exchanges[name] = type_
            return name

        async def declare_queue(self, name, durable=False, arguments=None):
            q = FakeQueue()
            self.queues[name] = (durable, arguments)
            return q

    channel = FakeChannel()
    await declare_topology(channel)
    assert "ai_tasks" in channel.exchanges
    assert "ai_tasks.dlx" in channel.exchanges
    assert "ai_tasks.workers" in channel.queues
    assert "ai_tasks.dead" in channel.queues
    assert channel.queues["ai_tasks.workers"][1]["x-dead-letter-exchange"] == "ai_tasks.dlx"


def test_publisher_holder_singleton():
    assert publisher_holder.publisher is publisher_holder.publisher
