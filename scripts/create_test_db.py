"""创建/重建测试数据库：python scripts/create_test_db.py"""
import asyncio
import os

import asyncpg

SERVER_DSN = os.environ.get("PG_SERVER_DSN", "postgresql://postgres:postgres@localhost:5435/postgres")
TEST_DB = os.environ.get("TEST_DB_NAME", "ai_backend_test")


async def main() -> None:
    conn = await asyncpg.connect(SERVER_DSN)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)')
        await conn.execute(f"CREATE DATABASE {TEST_DB}")
        print(f"test database ready: {TEST_DB}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
