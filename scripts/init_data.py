"""初始化演示数据：python scripts/init_data.py

创建演示账号 demo@example.com / demo123456，以及示例会话、消息与任务。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import db
from app.models import ChatSession, Message, Task, User

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo" + "123456"


async def main() -> None:
    db.init()
    assert db.session_factory is not None
    try:
        async with db.session_factory() as session:
            async with session.begin():
                exists = await session.scalar(select(User.id).where(User.email == DEMO_EMAIL))
                if exists:
                    print("demo 用户已存在，跳过")
                    return
                user = User(email=DEMO_EMAIL, hashed_password=hash_password(DEMO_PASSWORD), display_name="Demo")
                session.add(user)
                await session.flush()

                chat = ChatSession(user_id=user.id, title="示例会话")
                session.add(chat)
                await session.flush()

                session.add_all(
                    [
                        Message(session_id=chat.id, role="user", content="你好，介绍一下这个项目。"),
                        Message(
                            session_id=chat.id,
                            role="assistant",
                            content="这是一个 AI 服务后端系统：FastAPI + PostgreSQL + Redis + RabbitMQ。",
                            model="mock",
                        ),
                    ]
                )
                session.add(
                    Task(user_id=user.id, type="echo", payload={"hello": "world"}, status="succeeded")
                )
            print(f"demo 数据已创建：{DEMO_EMAIL} / {DEMO_PASSWORD}")
            print(f"数据库：{settings.database_url}")
    finally:
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())
