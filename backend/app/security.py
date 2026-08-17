from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PasswordResetToken, RevokedToken

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()

DecodeStatus = Literal["ok", "expired", "invalid"]


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    return pwd_context.verify(plain, hashed)


def create_access_token(
    *,
    user_id: str,
    role: str,
    email: str,
    full_name: str,
    student_id: str | None = None,
    grade: int | None = None,
    grades: list[int] | None = None,
    sections: list[str] | None = None,
    expires_minutes: int | None = None,
) -> tuple[str, datetime, str]:
    """
    Returns (token, expires_at, jti).
    JWT max lifetime capped at 6 hours via settings.
    """
    minutes = expires_minutes or settings.access_token_expire_minutes
    minutes = min(max(1, minutes), 360)
    expire = datetime.utcnow() + timedelta(minutes=minutes)
    jti = str(uuid.uuid4())
    role_norm = "teacher" if role == "educator" else role

    payload: dict[str, Any] = {
        "sub": user_id,
        "student_id": (student_id or user_id) if role_norm == "student" else None,
        "role": role_norm,
        "email": email,
        "name": full_name,
        "jti": jti,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    if role_norm == "student" and grade is not None:
        payload["grade"] = grade
    if role_norm == "teacher":
        if grades is not None:
            payload["grades"] = grades
        if sections is not None:
            payload["sections"] = sections

    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expire, jti


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def classify_token(token: str) -> tuple[DecodeStatus, dict[str, Any] | None]:
    """Distinguish expired vs invalid so the client can send users back to login."""
    try:
        return "ok", decode_token(token)
    except ExpiredSignatureError:
        return "expired", None
    except JWTError:
        return "invalid", None


def is_token_revoked(db: Session, jti: str | None) -> bool:
    if not jti:
        return True
    row = db.query(RevokedToken).filter(RevokedToken.jti == jti).first()
    return row is not None


def revoke_token(db: Session, *, jti: str, user_id: str, expires_at: datetime) -> None:
    if db.query(RevokedToken).filter(RevokedToken.jti == jti).first():
        return
    db.add(RevokedToken(jti=jti, user_id=user_id, expires_at=expires_at))
    db.commit()


def safe_decode(token: str) -> dict[str, Any] | None:
    status, payload = classify_token(token)
    return payload if status == "ok" else None


def _hash_reset_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_password_reset_token(db: Session, user_id: str) -> str:
    """Invalidate older unused tokens, create a new one, return raw token once."""
    now = datetime.utcnow()
    old = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
        )
        .all()
    )
    for row in old:
        row.used_at = now

    raw = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            user_id=user_id,
            token_hash=_hash_reset_token(raw),
            expires_at=now + timedelta(minutes=settings.password_reset_expire_minutes),
        )
    )
    db.commit()
    return raw


def consume_password_reset_token(db: Session, raw_token: str) -> str | None:
    """
    Validate and mark a reset token used.
    Returns user_id on success, None on failure.
    """
    if not raw_token or not raw_token.strip():
        return None
    now = datetime.utcnow()
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == _hash_reset_token(raw_token.strip()))
        .first()
    )
    if not row or row.used_at is not None or row.expires_at < now:
        return None
    row.used_at = now
    db.commit()
    return row.user_id
