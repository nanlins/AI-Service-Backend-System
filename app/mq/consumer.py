from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.db.session import db, redis_holder
from app.llm.base import get_llm
from app.models.task import TASK_FAILED, TASK_PENDING, TASK_RUNNING, TASK_SUCCEEDED, Task
from app.mq.delayed import enqueue_retry, pop_ready_retries
from app.mq.publisher import TaskPublisher
from app.mq.topology import declare_topology
from app.services.task_service import finalize_task

logger = logging.getLogger(__name__)


async def handle_summarize(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("text")
    if not text:
        raise AppError("payload.text 不能为空")
    max_length = int(payload.get("max_length", 200))
    llm = get_llm()
    resp = await llm.complete(
        [
            {"role": "system", "content": f"你是文本摘要助手。请对用户提供的文本生成不超过 {max_length} 字的简洁中文摘要。"},
            {"role": "user", "content": str(text)},
        ]
    )
    return {"summary": resp.content, "model": resp.model, "tokens": resp.completion_tokens}


async def handle_translate(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("text")
    if not text:
        raise AppError("payload.text 不能为空")
    target_lang = payload.get("target_lang", "en")
    llm = get_llm()
    resp = await llm.complete(
        [
            {"role": "system", "content": f"你是翻译助手。请把用户输入的文本翻译成 {target_lang}，只输出译文。"},
            {"role": "user", "content": str(text)},
        ]
    )
    return {"translation": resp.content, "target_lang": target_lang, "model": resp.model}


async def handle_echo(payload: dict[str, Any]) -> dict[str, Any]:
    return {"echo": payload}


TASK_HANDLERS = {
    "summarize": handle_summarize,
    "translate": handle_translate,
    "echo": handle_echo,
}


async def claim_task(session: AsyncSession, task_id: int) -> bool:
    """CAS 认领任务：仅 pending -> running 成功才返回 True（防重复消费）。"""
    result = await session.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == TASK_PENDING)
        .values(status=TASK_RUNNING, started_at=datetime.now(UTC))
    )
    await session.commit()
    return bool(getattr(result, "rowcount", 0))


async def _sync_status(redis: Redis | None, task_id: int, status: str) -> None:
    if redis is None:
        return
    key = f"task:{task_id}"
    await redis.hset(key, "status", status)
    await redis.expire(key, settings.task_status_ttl)


async def handle_task(
    task_id: int,
    redis: Redis | None = None,
    publisher: TaskPublisher | None = None,
) -> None:
    """执行单个任务：认领 -> 执行 -> 落库 -> 同步 Redis；失败按重试策略处理。"""
    if db.session_factory is None:
        db.init()
    assert db.session_factory is not None
    redis = redis if redis is not None else redis_holder.client

    async with db.session_factory() as session:
        if not await claim_task(session, task_id):
            logger.info("task %s 已被处理或非 pending 状态，跳过", task_id)
            return
        task = await session.get(Task, task_id)
        if task is None:
            return
        claimed_at = task.started_at or datetime.now(UTC)
        base_retry = task.retry_count
        await _sync_status(redis, task_id, TASK_RUNNING)

        handler = TASK_HANDLERS.get(task.type)
        retriable = False
        result: dict | None = None
        error: dict | None = None
        try:
            if handler is None:
                raise AppError(f"未知任务类型: {task.type}")
            result = await handler(task.payload)
            status, retry_count = TASK_SUCCEEDED, base_retry
        except Exception as exc:
            retry_count = base_retry + 1
            code = getattr(exc, "code", "internal_error")
            error = {"code": code, "message": str(exc)}
            if retry_count < settings.task_max_retries:
                status, retriable = TASK_PENDING, True
            else:
                status = TASK_FAILED
                logger.exception("task %s 重试耗尽，标记失败", task_id)

        # CAS 写回：执行期间若被 reaper 复位并被其他 worker 认领，丢弃本地结果防覆盖
        owned = await finalize_task(session, task_id, claimed_at, status, result, error, retry_count)
        if not owned:
            logger.warning("task %s 执行期间所有权丢失（可能被补偿扫描复位重投），丢弃本地结果", task_id)
            return
        await _sync_status(redis, task_id, status)

    if retriable:
        if redis is not None:
            # 指数退避延迟重投：写入 Redis 延迟队列，由 worker 内 pump 到点重投
            await enqueue_retry(redis, task_id, retry_count)
        elif publisher is not None:
            try:
                await publisher.publish_task(task_id, task.type)
            except Exception:
                logger.exception("task %s 重投失败，等待补偿扫描", task_id)


class TaskConsumer:
    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.rabbitmq_url
        self._connection: aio_pika.abc.AbstractConnection | None = None
        self.publisher = TaskPublisher(url)

    async def start(self) -> None:
        await self.publisher.connect()
        self._connection = await aio_pika.connect_robust(self._url)
        channel = await self._connection.channel()
        await channel.set_qos(prefetch_count=settings.worker_prefetch)
        await declare_topology(channel)
        queue = await channel.get_queue(settings.task_queue)
        await queue.consume(self._on_message)
        logger.info("worker 开始消费队列 %s", settings.task_queue)

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        async with message.process(requeue=False, reject_on_redelivered=False):
            body = json.loads(message.body)
            task_id = int(body["task_id"])
            redis = redis_holder.client
            lock_key = f"lock:task:{task_id}"
            locked = False
            if redis is not None:
                locked = bool(await redis.set(lock_key, "1", nx=True, ex=settings.task_lock_ttl))
                if not locked:
                    logger.info("task %s 正在被其他 worker 处理，跳过", task_id)
                    return
            try:
                await handle_task(task_id, redis=redis, publisher=self.publisher)
            finally:
                if redis is not None and locked:
                    await redis.delete(lock_key)

    async def stop(self) -> None:
        if self._connection is not None:
            await self._connection.close()
        await self.publisher.close()


async def run_worker() -> None:
    db.init()
    redis_holder.init()
    consumer = TaskConsumer()

    async def _reaper_loop() -> None:
        """定时补偿扫描：复位 running 超时任务，防止 worker 崩溃后任务永久卡死。"""
        from app.services.task_service import reap_stale_tasks

        while True:
            await asyncio.sleep(settings.task_reap_interval)
            try:
                assert db.session_factory is not None
                async with db.session_factory() as session:
                    await reap_stale_tasks(session, redis_holder.client)
            except Exception:
                logger.exception("补偿扫描失败")

    async def _retry_pump_loop() -> None:
        """延迟队列 pump：把到期的重试任务重新投递到 RabbitMQ。"""
        while True:
            await asyncio.sleep(settings.task_retry_pump_interval)
            try:
                if redis_holder.client is None:
                    continue
                ready_ids = await pop_ready_retries(redis_holder.client)
                for task_id in ready_ids:
                    # 重新读库拿任务类型构造 routing_key；读不到就跳过（任务可能已被删除）
                    try:
                        assert db.session_factory is not None
                        async with db.session_factory() as session:
                            task = await session.get(Task, task_id)
                            if task is None or task.status != TASK_PENDING:
                                logger.info("task %s 已不处于 pending，跳过延迟重投", task_id)
                                continue
                            await consumer.publisher.publish_task(task.id, task.type)
                    except Exception:
                        logger.exception("延迟重投 task %s 失败", task_id)
                        # 重投失败重新入队，避免任务永久丢失
                        try:
                            if redis_holder.client is not None:
                                await enqueue_retry(redis_holder.client, task_id, 1)
                        except Exception:
                            logger.exception("task %s 重新入队失败", task_id)
            except Exception:
                logger.exception("延迟队列 pump 失败")

    await consumer.start()
    reaper = asyncio.create_task(_reaper_loop())
    pump = asyncio.create_task(_retry_pump_loop())
    try:
        await asyncio.Event().wait()
    finally:
        pump.cancel()
        reaper.cancel()
        await consumer.stop()
        await redis_holder.close()
        await db.dispose()
