from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.errors import NotFoundError
from app.models.session import ChatSession
from app.models.user import User
from app.schemas.common import Page
from app.schemas.session import SessionCreate, SessionOut, SessionUpdate

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=201)
async def create_session(
    data: SessionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = ChatSession(
        user_id=user.id,
        title=data.title or "新会话",
        system_prompt=data.system_prompt,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("", response_model=Page[SessionOut])
async def list_sessions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base = select(ChatSession).where(ChatSession.user_id == user.id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    items = (
        await db.scalars(base.order_by(ChatSession.updated_at.desc()).offset((page - 1) * page_size).limit(page_size))
    ).all()
    return Page(items=list(items), total=int(total or 0), page=page, page_size=page_size)


async def _get_owned_session(db: AsyncSession, user_id: int, session_id: int) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None or session.user_id != user_id:
        raise NotFoundError("会话不存在")
    return session


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _get_owned_session(db, user.id, session_id)


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: int,
    data: SessionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_owned_session(db, user.id, session_id)
    if data.title is not None:
        session.title = data.title
    if data.system_prompt is not None:
        session.system_prompt = data.system_prompt
    await db.commit()
    await db.refresh(session)
    return session


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_owned_session(db, user.id, session_id)
    await db.delete(session)
    await db.commit()
