import time

import fakeredis.aioredis

from app.core.ratelimit import sliding_window_limiter


async def test_allows_within_limit():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    allowed = True
    for _ in range(3):
        ok, retry_after = await sliding_window_limiter(r, "rl:t:1", 3, 60)
        allowed = allowed and ok
    assert allowed
    assert retry_after == 0


async def test_blocks_over_limit():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    for _ in range(3):
        await sliding_window_limiter(r, "rl:t:1", 3, 60)
    ok, retry_after = await sliding_window_limiter(r, "rl:t:1", 3, 60)
    assert not ok
    assert retry_after > 0


async def test_window_slides_and_resets():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    now = time.time()
    for _ in range(3):
        await sliding_window_limiter(r, "rl:t:1", 3, 60, now=now)
    ok, _ = await sliding_window_limiter(r, "rl:t:1", 3, 60, now=now + 61)
    assert ok  # 窗口滑动后旧计数被清出


async def test_keys_isolated_per_user():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    for _ in range(3):
        await sliding_window_limiter(r, "rl:u:1", 3, 60)
    ok, _ = await sliding_window_limiter(r, "rl:u:2", 3, 60)
    assert ok
