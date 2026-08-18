from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthError, ConflictError
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import RegisterIn


async def register_user(db: AsyncSession, data: RegisterIn) -> User:
    existing = await db.scalar(select(User).where(User.email == data.email))
    if existing is not None:
        raise ConflictError("该邮箱已被注册")
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        display_name=data.display_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.hashed_password):
        raise AuthError("邮箱或密码错误")
    if user.status != "active":
        raise AuthError("用户已被禁用")
    return user
