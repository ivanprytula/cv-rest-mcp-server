"""User ORM row (ADR-023) — persistence layer, Alembic-migrated schema."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from services.portfolio.auth.user import ROLE_USER, User
from services.portfolio.db import Base


class UserRow(Base):
    """ORM row. `hashed_password` is internal; expose via `.to_domain()`."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_USER)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    def to_domain(self) -> User:
        return User(
            id=self.id,
            username=self.username,
            email=self.email,
            is_active=self.is_active,
            role=self.role,
        )
