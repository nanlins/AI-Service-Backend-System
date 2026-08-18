"""简单压测脚本：python scripts/load_test.py [并发数] [任务总数]

流程：注册/登录 -> 并发创建 echo 任务 -> 轮询至终态 -> 输出延迟统计。
"""
import asyncio
import statistics
import sys
import time
import uuid

import httpx

BASE_URL = "http://localhost:8000/api/v1"


async def register_and_login(client: httpx.AsyncClient) -> str:
    email = f"load_{uuid.uuid4().hex[:8]}@example.com"
    password = "loadtest123"
    resp = await client.post(f"{BASE_URL}/auth/register", json={"email": email, "password": password})
    resp.raise_for_status()
    resp = await client.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]


async def run_one_task(client: httpx.AsyncClient, headers: dict) -> float:
    start = time.perf_counter()
    resp = await client.post(
        f"{BASE_URL}/tasks",
        headers=headers,
        json={"type": "echo", "payload": {"ping": "pong"}},
    )
    resp.raise_for_status()
    task_id = resp.json()["id"]
    while True:
        await asyncio.sleep(0.2)
        resp = await client.get(f"{BASE_URL}/tasks/{task_id}", headers=headers)
        resp.raise_for_status()
        status = resp.json()["status"]
        if status in {"succeeded", "failed", "cancelled"}:
            break
        if time.perf_counter() - start > 30:
            raise TimeoutError(f"task {task_id} 超时未完成")
    return time.perf_counter() - start


async def main() -> None:
    concurrency = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    total = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    async with httpx.AsyncClient(timeout=30) as client:
        token = await register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        sem = asyncio.Semaphore(concurrency)

        async def limited() -> float:
            async with sem:
                return await run_one_task(client, headers)

        t0 = time.perf_counter()
        latencies = await asyncio.gather(*[limited() for _ in range(total)])
        elapsed = time.perf_counter() - t0

    latencies = sorted(latencies)
    print(f"任务总数: {total}  并发: {concurrency}")
    print(f"总耗时: {elapsed:.2f}s  QPS: {total / elapsed:.2f}")
    print(f"延迟 avg={statistics.mean(latencies):.2f}s  p50={latencies[len(latencies) // 2]:.2f}s  "
          f"p95={latencies[int(len(latencies) * 0.95)]:.2f}s  max={latencies[-1]:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
