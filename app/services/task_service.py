from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, UpstreamError
from app.models.task import (
    TASK_CANCELLED,
    TASK_FAILED,
    TASK_PENDING,
    TASK_RUNNING,
    TASK_SUCCEEDED,
    Task,
)
from app.mq.publisher import TaskPublisher
from app.schemas.task import TaskCreate

logger = logging.getLogger(__name__)


async def create_task(
    db: AsyncSession,
    redis: Redis,
    publisher: TaskPublisher,
    user_id: int,
    data: TaskCreate,
    idempotency_key: str | None = None,
) -> Task:
    if idempotency_key:
        cached_id = await redis.get(f"idem:{user_id}:{idempotency_key}")
        if cached_id:
            existing = await db.get(Task, int(cached_id))
            if existing is not None:
                return existing

    task = Task(
        user_id=user_id,
        session_id=data.session_id,
        type=data.type,
        payload=data.payload,
        priority=data.priority,
        idempotency_key=idempotency_key,
    )
    db.add(task)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(Task).where(Task.user_id == user_id, Task.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing
        raise
    await db.refresh(task)

    if idempotency_key:
        await redis.set(f"idem:{user_id}:{idempotency_key}", str(task.id), ex=86400)

    try:
        await publisher.publish_task(task.id, task.type)
    except Exception as exc:
        logger.exception("任务 %s 发布到消息队列失败", task.id)
        raise UpstreamError("任务队列暂不可用，请稍后重试") from exc

    key = f"task:{task.id}"
    await redis.hset(key, mapping={"status": task.status, "progress": "0"})
    await redis.expire(key, settings.task_status_ttl)
    return task


async def get_task(db: AsyncSession, user_id: int, task_id: int) -> Task:
    """查询任务：DB 为权威数据源；Redis 中保存 worker 同步的状态快照用于快速轮询。"""
    task = await db.get(Task, task_id)
    if task is None or task.user_id != user_id:
        raise NotFoundError("任务不存在")
    return task


async def get_task_status_snapshot(redis: Redis, task_id: int) -> dict[str, str]:
    raw = await redis.hgetall(f"task:{task_id}")
    return {str(k): str(v) for k, v in raw.items()}


async def list_tasks(
    db: AsyncSession, user_id: int, page: int = 1, page_size: int = 20, status: str | None = None
) -> tuple[list[Task], int]:
    query = select(Task).where(Task.user_id == user_id)
    if status:
        query = query.where(Task.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    items = (
        await db.scalars(query.order_by(Task.id.desc()).offset((page - 1) * page_size).limit(page_size))
    ).all()
    return list(items), int(total or 0)


async def cancel_task(db: AsyncSession, redis: Redis, user_id: int, task_id: int) -> Task:
    task = await db.get(Task, task_id)
    if task is None or task.user_id != user_id:
        raise NotFoundError("任务不存在")
    if task.status != TASK_PENDING:
        raise ConflictError(f"当前状态 {task.status} 不可取消，仅 pending 任务可取消")
    task.status = TASK_CANCELLED
    await db.commit()
    await db.refresh(task)
    # 同步 Redis 状态快照，避免 /tasks/{id}/status 轮询读到过期的 pending
    key = f"task:{task_id}"
    await redis.hset(key, mapping={"status": task.status})
    await redis.expire(key, settings.task_status_ttl)
    return task


async def finalize_task(
    db: AsyncSession,
    task_id: int,
    claimed_at: datetime,
    status: str,
    result: dict | None,
    error: dict | None,
    retry_count: int,
) -> bool:
    """CAS 写回：仅当本 worker 仍拥有任务（status=running 且 started_at 与认领时一致）才落库。

    reaper 复位 + 另一 worker 认领后，started_at/status 已变化 → rowcount=0，
    本地结果被丢弃，防止旧 worker 覆盖新 worker 的状态（reaper/CAS 边界竞态的第二道保险）。
    """
    values: dict[str, Any] = {
        "status": status,
        "result": result,
        "error": error,
        "retry_count": retry_count,
    }
    if status in {TASK_SUCCEEDED, TASK_FAILED}:
        values["finished_at"] = datetime.now(UTC)
    upd = await db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == TASK_RUNNING, Task.started_at == claimed_at)
        .values(**values)
    )
    await db.commit()
    return bool(getattr(upd, "rowcount", 0))


async def reap_stale_tasks(db: AsyncSession, redis: Redis | None = None, stale_seconds: int | None = None) -> int:
    """补偿扫描（docs §6.3）：把停留 running 超过阈值的任务重置回 pending，使其可被重新认领。

    worker 崩溃/消息重投但 CAS 失败时，任务会卡在 running；此函数定期把它们复位。
    返回被复位的任务数。
    """
    stale_seconds = stale_seconds or settings.task_reap_stale_seconds
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    result = await db.execute(
        update(Task)
        .where(Task.status == TASK_RUNNING, Task.started_at < cutoff)
        .values(status=TASK_PENDING, started_at=None)
        .returning(Task.id)
    )
    await db.commit()
    task_ids = [row[0] for row in result.all()]
    if redis is not None:
        for task_id in task_ids:
            key = f"task:{task_id}"
            await redis.hset(key, mapping={"status": TASK_PENDING})
            await redis.expire(key, settings.task_status_ttl)
    if task_ids:
        logger.info("补偿扫描：%d 个 running 超时任务已复位为 pending", len(task_ids))
    return len(task_ids)
