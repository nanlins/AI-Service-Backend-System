from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_db
from app.core.ratelimit import ip_rate_limit
from app.core.security import create_access_token
from app.schemas.auth import LoginIn, RegisterIn, TokenOut
from app.schemas.user import UserOut
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])

_register_limiter = ip_rate_limit("auth_register", settings.rate_limit_auth_attempts, settings.rate_limit_auth_window)
_login_limiter = ip_rate_limit("auth_login", settings.rate_limit_auth_attempts, settings.rate_limit_auth_window)


@router.post("/register", response_model=UserOut, status_code=201, dependencies=[Depends(_register_limiter)])
async def register(data: RegisterIn, db: AsyncSession = Depends(get_db)):
    return await user_service.register_user(db, data)


@router.post("/login", response_model=TokenOut, dependencies=[Depends(_login_limiter)])
async def login(data: LoginIn, db: AsyncSession = Depends(get_db)):
    user = await user_service.authenticate_user(db, data.email, data.password)
    return TokenOut(access_token=create_access_token(user.id))
