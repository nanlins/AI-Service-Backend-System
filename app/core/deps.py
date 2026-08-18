from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthError, ForbiddenError
from app.core.security import decode_access_token
from app.db.session import get_db, get_redis
from app.models.user import User
from app.mq.publisher import TaskPublisher, publisher_holder

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise AuthError("缺少访问令牌")
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id or not str(user_id).isdigit():
        raise AuthError("访问令牌无效")
    user = await db.get(User, int(user_id))
    if user is None:
        raise AuthError("用户不存在")
    if user.status != "active":
        raise ForbiddenError("用户已被禁用")
    return user


def get_publisher() -> TaskPublisher:
    return publisher_holder.publisher


__all__ = ["get_current_user", "get_db", "get_publisher", "get_redis"]
