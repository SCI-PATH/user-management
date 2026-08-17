from __future__ import annotations

"""Small helpers for consistent API error payloads the frontend can route on."""

from typing import Any, Literal

from fastapi import HTTPException, status

AuthAction = Literal["login", "none"]


def auth_error(
    *,
    code: str,
    message: str,
    http_status: int = status.HTTP_401_UNAUTHORIZED,
    action: AuthAction = "login",
    extra: dict[str, Any] | None = None,
) -> HTTPException:
    detail: dict[str, Any] = {
        "code": code,
        "message": message,
        "action": action,
    }
    if extra:
        detail.update(extra)
    return HTTPException(status_code=http_status, detail=detail)


def client_error(
    *,
    code: str,
    message: str,
    http_status: int = status.HTTP_400_BAD_REQUEST,
    extra: dict[str, Any] | None = None,
) -> HTTPException:
    detail: dict[str, Any] = {"code": code, "message": message, "action": "none"}
    if extra:
        detail.update(extra)
    return HTTPException(status_code=http_status, detail=detail)
