from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_publisher, get_redis
from app.mq.publisher import TaskPublisher

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    publisher: TaskPublisher = Depends(get_publisher),
):
    checks: dict[str, bool] = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = True
    except Exception:
        checks["postgres"] = False
    try:
        checks["redis"] = bool(await redis.ping())
    except Exception:
        checks["redis"] = False
    checks["rabbitmq"] = publisher.is_ready
    ready = all(checks.values())
    return {"status": "ok" if ready else "degraded", "checks": checks}
