from fastapi import APIRouter, Depends, Header, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, get_publisher, get_redis
from app.models.user import User
from app.mq.publisher import TaskPublisher
from app.schemas.common import Page
from app.schemas.task import TaskCreate, TaskOut
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut, status_code=202)
async def create_task(
    body: TaskCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    publisher: TaskPublisher = Depends(get_publisher),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return await task_service.create_task(db, redis, publisher, user.id, body, idempotency_key)


@router.get("", response_model=Page[TaskOut])
async def list_tasks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await task_service.list_tasks(db, user.id, page, page_size, status)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await task_service.get_task(db, user.id, task_id)


@router.get("/{task_id}/status")
async def get_task_status_snapshot(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Redis 中的任务状态快照（worker 实时同步），用于高频轮询。"""
    await task_service.get_task(db, user.id, task_id)
    snapshot = await task_service.get_task_status_snapshot(redis, task_id)
    return {"task_id": task_id, "snapshot": snapshot}


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    return await task_service.cancel_task(db, redis, user.id, task_id)
