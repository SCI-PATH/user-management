from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """Maps to team shared.users (account row)."""

    __tablename__ = "users"
    __table_args__ = {"schema": "shared"}

    id: Mapped[str] = mapped_column("user_id", String(64), primary_key=True, default=_uuid)
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # learner | teacher | ...
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=False, index=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # App-facing alias used across routers/serializers
    full_name = synonym("username")

    student_profile: Mapped[StudentProfile | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="StudentProfile.user_id",
    )
    educator_profile: Mapped[EducatorProfile | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        primaryjoin="User.id==EducatorProfile.user_id",
        foreign_keys="EducatorProfile.user_id",
    )

    # Not in shared.users — kept in-memory for Google/password flows
    @property
    def auth_provider(self) -> str:
        return getattr(self, "_auth_provider", "password")

    @auth_provider.setter
    def auth_provider(self, value: str | None) -> None:
        self._auth_provider = value or "password"

    @property
    def google_sub(self) -> str | None:
        return getattr(self, "_google_sub", None)

    @google_sub.setter
    def google_sub(self, value: str | None) -> None:
        self._google_sub = value


class StudentProfile(Base):
    """Maps to shared.learners (grade / display name for a learner account)."""

    __tablename__ = "learners"
    __table_args__ = {"schema": "shared"}

    learner_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(
        "account_user_id",
        String(64),
        ForeignKey("shared.users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    grade: Mapped[int | None] = mapped_column("grade_level", SmallInteger, nullable=True)
    class_section: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    user: Mapped[User | None] = relationship(
        back_populates="student_profile",
        foreign_keys=[user_id],
    )

    # Not present on shared.learners — API still accepts the field but it is not persisted
    @property
    def prev_year_science_marks(self) -> float | None:
        return getattr(self, "_prev_year_science_marks", None)

    @prev_year_science_marks.setter
    def prev_year_science_marks(self, value: float | None) -> None:
        self._prev_year_science_marks = value

    @property
    def metadata_json(self) -> str | None:
        return getattr(self, "_metadata_json", None)

    @metadata_json.setter
    def metadata_json(self, value: str | None) -> None:
        self._metadata_json = value


class ClassRoom(Base):
    """Teacher-owned class in the shared cross-component schema."""

    __tablename__ = "classes"
    __table_args__ = {"schema": "shared"}

    class_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    teacher_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("shared.users.user_id"), nullable=False, index=True
    )
    class_name: Mapped[str] = mapped_column(String(255), nullable=False)
    grade_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    subject: Mapped[str] = mapped_column(String(64), nullable=False, default="Science")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class ClassEnrollment(Base):
    """Learner membership; source of truth for classroom rosters."""

    __tablename__ = "class_enrollments"
    __table_args__ = (
        UniqueConstraint("class_code", "learner_id"),
        {"schema": "shared"},
    )

    enrollment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    class_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("shared.classes.class_code"), nullable=False, index=True
    )
    learner_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("shared.learners.learner_id"), nullable=False, index=True
    )
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class EducatorProfile(Base):
    """Teacher extras — owned by content_generation schema (not in shared)."""

    __tablename__ = "educator_profiles"
    __table_args__ = {"schema": "content_generation"}

    # No DB FK: Neon role cannot REFERENCE shared.users; integrity enforced in app
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    grades_taught: Mapped[str] = mapped_column(String(64), default="")
    class_sections: Mapped[str] = mapped_column(String(255), default="")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(
        back_populates="educator_profile",
        primaryjoin="User.id==EducatorProfile.user_id",
        foreign_keys=[user_id],
    )


class RevokedToken(Base):
    """JWT jti blocklist until natural expiry (logout support)."""

    __tablename__ = "revoked_tokens"
    __table_args__ = (
        UniqueConstraint("jti", name="uq_revoked_jti"),
        {"schema": "content_generation"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    jti: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PasswordResetToken(Base):
    """One-time tokens for forgot-password / reset-password."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = {"schema": "content_generation"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
