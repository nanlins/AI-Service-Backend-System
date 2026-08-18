from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:dev_pg_pw_001@localhost:5435/ai_backend_test")
os.environ.setdefault("AUTO_MIGRATE", "false")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("LLM_MOCK_DELAY", "0")
os.environ.setdefault("LLM_MOCK_STREAM_DELAY", "0")
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import NullPool  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

import app.models  # noqa: E402,F401
from app.core import deps  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import db  # noqa: E402
from app.main import create_app  # noqa: E402

TEST_DB_URL = os.environ["DATABASE_URL"]
TEST_PASSWORD = "demo" + "123456"

_state: dict = {"engine": None, "loop": None}


async def _ensure_db() -> None:
    """每个事件循环独立初始化引擎（pytest-asyncio 默认每测试一个新循环）。"""
    loop = asyncio.get_running_loop()
    if _state["loop"] is not loop:
        engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
        _state["engine"], _state["loop"] = engine, loop
        db.engine = engine
        db.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(autouse=True)
async def _clean_db():
    await _ensure_db()
    assert db.engine is not None
    async with db.engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    yield


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


class FakePublisher:
    """测试替身：只记录发布的消息，不连接真实 MQ。"""

    def __init__(self) -> None:
        self.published: list[dict] = []

    @property
    def is_ready(self) -> bool:
        return True

    async def publish_task(self, task_id: int, task_type: str) -> None:
        self.published.append({"task_id": task_id, "task_type": task_type})

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass


@pytest.fixture
def fake_publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
async def app(fake_redis, fake_publisher):
    application = create_app()
    application.dependency_overrides[deps.get_redis] = lambda: fake_redis
    application.dependency_overrides[deps.get_publisher] = lambda: fake_publisher
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    await client.post(
        f"{settings.api_v1_prefix}/auth/register",
        json={"email": "tester@example.com", "password": TEST_PASSWORD, "display_name": "Tester"},
    )
    resp = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        json={"email": "tester@example.com", "password": TEST_PASSWORD},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
