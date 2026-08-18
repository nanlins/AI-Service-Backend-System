from __future__ import annotations

import time
import uuid

from fastapi import Depends, Request
from redis.asyncio import Redis

from app.core.deps import get_current_user, get_redis
from app.core.errors import RateLimitError
from app.models.user import User


async def sliding_window_limiter(
    redis: Redis, key: str, limit: int, window: int, now: float | None = None
) -> tuple[bool, int]:
    """Redis 滑动窗口限流（ZSet）：返回 (是否放行, 建议 Retry-After 秒数)。

    每次请求 zadd 一个成员并把窗口外的成员清掉，member 数即窗口内请求数。
    """
    now = now if now is not None else time.time()
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now - window)
    pipe.zadd(key, {uuid.uuid4().hex: now})
    pipe.zcard(key)
    pipe.zrange(key, 0, 0, withscores=True)
    pipe.expire(key, window + 5)
    _, _, count, oldest, _ = await pipe.execute()
    allowed = int(count) <= limit
    retry_after = 0
    if not allowed and oldest:
        retry_after = max(1, int(window - (now - float(oldest[0][1]))))
    return allowed, retry_after


def ip_rate_limit(key_prefix: str, limit: int, window: int):
    """按客户端 IP 限流（用于 /auth/register、/auth/login 等匿名接口）。"""

    async def dependency(request: Request, redis: Redis = Depends(get_redis)):
        ip = request.client.host if request.client else "unknown"
        allowed, retry_after = await sliding_window_limiter(
            redis, f"rl:{key_prefix}:{ip}", limit, window
        )
        if not allowed:
            raise RateLimitError(detail={"retry_after": retry_after}, retry_after=retry_after)

    return dependency


def user_rate_limit(key_prefix: str, limit: int, window: int):
    """按已认证用户限流（用于对话等受保护接口）。"""

    async def dependency(
        user: User = Depends(get_current_user), redis: Redis = Depends(get_redis)
    ):
        allowed, retry_after = await sliding_window_limiter(
            redis, f"rl:{key_prefix}:{user.id}", limit, window
        )
        if not allowed:
            raise RateLimitError(detail={"retry_after": retry_after}, retry_after=retry_after)

    return dependency
