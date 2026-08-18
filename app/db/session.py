from __future__ import annotations

from collections.abc import AsyncIterator

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


class Database:
    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    def init(self, url: str | None = None, pool_size: int | None = None, max_overflow: int | None = None) -> None:
        if self.engine is not None:
            return
        self.engine = create_async_engine(
            url or settings.database_url,
            pool_size=pool_size or settings.db_pool_size,
            max_overflow=max_overflow or settings.db_max_overflow,
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None
            self.session_factory = None

    @property
    def ready(self) -> bool:
        return self.engine is not None


class RedisHolder:
    def __init__(self) -> None:
        self.client: Redis | None = None

    def init(self, url: str | None = None) -> None:
        if self.client is None:
            self.client = Redis.from_url(url or settings.redis_url, decode_responses=True)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    @property
    def ready(self) -> bool:
        return self.client is not None


db = Database()
redis_holder = RedisHolder()


async def get_db() -> AsyncIterator[AsyncSession]:
    if db.session_factory is None:
        db.init()
    assert db.session_factory is not None
    async with db.session_factory() as session:
        yield session


def get_redis() -> Redis:
    if redis_holder.client is None:
        redis_holder.init()
    assert redis_holder.client is not None
    return redis_holder.client
