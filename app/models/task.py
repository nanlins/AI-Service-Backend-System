from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User

TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_SUCCEEDED = "succeeded"
TASK_FAILED = "failed"
TASK_CANCELLED = "cancelled"

TASK_TERMINAL_STATES = {TASK_SUCCEEDED, TASK_FAILED, TASK_CANCELLED}
TASK_TYPES = {"summarize", "translate", "echo"}


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_tasks_user_idempotency"),
        Index("idx_tasks_user_status", "user_id", "status"),
        Index("idx_tasks_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    session_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("sessions.id"))
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=TASK_PENDING)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=5)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="tasks")
