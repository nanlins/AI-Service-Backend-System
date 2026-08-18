from __future__ import annotations

import logging
import time

from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

RETRY_ZSET = "task:retry:delayed"


def retry_delay(retry_count: int) -> int:
    """指数退避：delay = min(max, base * 2^(retry-1))。"""
    return min(
        settings.task_retry_max_delay,
        settings.task_retry_base_delay * (2 ** (retry_count - 1)),
    )


async def enqueue_retry(redis: Redis, task_id: int, retry_count: int) -> int:
    """把需要重试的任务写入 Redis 延迟队列（ZSet：score=到期时间）。"""
    delay = retry_delay(retry_count)
    score = time.time() + delay
    await redis.zadd(RETRY_ZSET, {str(task_id): score})
    logger.info("task %s 延迟 %ss 后重投（第 %d 次重试）", task_id, delay, retry_count)
    return delay


async def pop_ready_retries(redis: Redis) -> list[int]:
    """取出到期任务（原子性由 worker 内的重投 pump 串行保证）。"""
    now = time.time()
    ids = await redis.zrangebyscore(RETRY_ZSET, 0, now)
    if not ids:
        return []
    await redis.zrem(RETRY_ZSET, *ids)
    return [int(str(x)) for x in ids]
