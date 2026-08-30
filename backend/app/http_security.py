"""Security middleware: rate limits and response headers."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def allow(self, key: str, *, limit: int, window_seconds: float) -> bool:
        now = time.monotonic()
        async with self._lock:
            bucket = [t for t in self._hits[key] if t > now - window_seconds]
            if len(bucket) >= limit:
                self._hits[key] = bucket
                return False
            bucket.append(now)
            self._hits[key] = bucket
            return True


_limiter = SlidingWindowLimiter()

UM_RATE_RULES: list[tuple[str, str, int, float]] = [
    ("/auth/login", "POST", 15, 60.0),
    ("/auth/signup/", "POST", 10, 60.0),
    ("/auth/forgot-password", "POST", 8, 60.0),
    ("/auth/reset-password", "POST", 10, 60.0),
    ("/classes/join", "POST", 20, 60.0),
    ("/students/", "GET", 120, 60.0),
]


def _rule_matches(path: str, method: str, prefix: str, rule_method: str) -> bool:
    if rule_method != "*" and method.upper() != rule_method.upper():
        return False
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(prefix + "/")


async def check_um_rate_limit(path: str, method: str, ip: str) -> bool:
    for prefix, rule_method, limit, window in UM_RATE_RULES:
        if _rule_matches(path, method, prefix, rule_method):
            key = f"{ip}:{method}:{prefix}"
            return await _limiter.allow(key, limit=limit, window_seconds=window)
    return True


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        ip = _client_ip(request)
        if not await check_um_rate_limit(request.url.path, request.method, ip):
            log.warning("rate_limit path=%s ip=%s", request.url.path, ip)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": {
                        "code": "rate_limited",
                        "message": "Too many requests. Please wait a moment and try again.",
                        "action": "none",
                    }
                },
            )
        return await call_next(request)
