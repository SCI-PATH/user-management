from __future__ import annotations

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import auth_error
from app.models import User
from app.security import classify_token, is_token_revoked

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not creds or not creds.credentials:
        raise auth_error(
            code="not_authenticated",
            message="Please log in to continue.",
            action="login",
        )
    status_kind, payload = classify_token(creds.credentials)
    if status_kind == "expired":
        raise auth_error(
            code="session_expired",
            message="Your session timed out. Please log in again.",
            action="login",
        )
    if status_kind != "ok" or not payload:
        raise auth_error(
            code="invalid_token",
            message="Invalid session. Please log in again.",
            action="login",
        )
    jti = payload.get("jti")
    if is_token_revoked(db, jti):
        raise auth_error(
            code="logged_out",
            message="You have been signed out. Please log in again.",
            action="login",
        )
    user_id = payload.get("sub")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise auth_error(
            code="user_inactive",
            message="Account not found or inactive. Please log in again.",
            action="login",
            http_status=status.HTTP_401_UNAUTHORIZED,
        )
    return user


def require_role(*roles: str):
    from app.errors import client_error
    from app.serializers import normalize_role

    allowed = {normalize_role(r) for r in roles}

    def _inner(user: User = Depends(get_current_user)) -> User:
        if normalize_role(user.role) not in allowed:
            raise client_error(
                code="forbidden_role",
                message="Not allowed for this role.",
                http_status=status.HTTP_403_FORBIDDEN,
            )
        return user

    return _inner
