from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.errors import NotFoundError
from app.core.ratelimit import user_rate_limit
from app.llm.base import SamplingParams
from app.models.message import Message
from app.models.session import ChatSession
from app.models.user import User
from app.schemas.message import MessageIn, MessageOut, ReplyOut
from app.services import chat_service

router = APIRouter(prefix="/sessions", tags=["messages"])

_message_limiter = user_rate_limit(
    "message", settings.rate_limit_message_attempts, settings.rate_limit_message_window
)


async def _get_owned_session(db: AsyncSession, user_id: int, session_id: int) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None or session.user_id != user_id:
        raise NotFoundError("会话不存在")
    return session


def _sampling(body: MessageIn) -> SamplingParams:
    return SamplingParams(
        temperature=body.temperature,
        top_p=body.top_p,
        max_tokens=body.max_tokens,
        stop=body.stop,
    )


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_session(db, user.id, session_id)
    rows = await db.scalars(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id)
        .offset(offset)
        .limit(limit)
    )
    return rows.all()


@router.post("/{session_id}/messages", response_model=ReplyOut, dependencies=[Depends(_message_limiter)])
async def send_message(
    session_id: int,
    body: MessageIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_owned_session(db, user.id, session_id)
    sampling = _sampling(body)
    if body.stream:
        return StreamingResponse(
            chat_service.stream_reply(db, session, body.content, model=body.model, sampling=sampling),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    user_message, assistant_message = await chat_service.reply(
        db, session, body.content, model=body.model, sampling=sampling
    )
    return ReplyOut(
        user_message=MessageOut.model_validate(user_message),
        assistant_message=MessageOut.model_validate(assistant_message),
    )
