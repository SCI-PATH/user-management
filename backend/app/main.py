from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.http_security import RateLimitMiddleware, SecurityHeadersMiddleware
from app.database import init_db
from app.routers import auth, classes, google_oauth, users
from app.schemas import HealthResponse

settings = get_settings()
log = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if settings.database_url.startswith("postgresql") and (
        settings.jwt_secret.startswith("change-me") or settings.jwt_secret.startswith("dev-change-me")
    ):
        log.warning("JWT_SECRET is still a placeholder — set a long random value in production")
    if settings.database_url.startswith("postgresql") and settings.expose_reset_token:
        log.warning("EXPOSE_RESET_TOKEN=true — disable in production")
    yield


OPENAPI_TAGS = [
    {
        "name": "auth",
        "description": (
            "Email/password signup & login, session checks, and logout. "
            "JWT access tokens expire in ≤ 6 hours."
        ),
    },
    {
        "name": "users",
        "description": (
            "Authenticated profile APIs. Students expose **full_name** and **grade** (6–9) "
            "via nested `student` and convenience `student_id`."
        ),
    },
    {
        "name": "students",
        "description": (
            "Public lightweight student summary for other microservices "
            "(Learning Path Engine, question engine, analytics): "
            "`student_id`, `full_name`, `grade`. No email or secrets."
        ),
    },
    {
        "name": "classes",
        "description": (
            "Teacher-owned classes, optional learner enrollment by class code, "
            "and grade-scoped rosters."
        ),
    },
    {
        "name": "health",
        "description": "Service health checks.",
    },
]

# Swagger (/docs) shows major / integration APIs only.
OPENAPI_INCLUDE_PATHS = {
    "/health",
    "/auth/signup/student",
    "/auth/signup/teacher",
    "/auth/login",
    "/auth/logout",
    "/auth/session",
    "/auth/me",
    "/users/me",
    "/students/{student_id}",
    "/classes",
    "/classes/mine",
    "/classes/join",
    "/classes/{class_code}/roster",
}


app = FastAPI(
    title=settings.app_name,
    version="0.3.1",
    description=(
        "## SCI-PATH User Management\n\n"
        "Auth & user profiles for students and teachers.\n\n"
        "**Swagger lists major integration APIs only** (signup/login, session, "
        "`GET /students/{id}`, profile, classes). Other routes still work at runtime.\n\n"
        "### Integration highlights\n"
        "- **Student identity for other services:** `GET /students/{student_id}` → "
        "`{ student_id, full_name, grade }`\n"
        "- **Own profile (JWT):** `GET /users/me` or `GET /auth/me` → includes "
        "`full_name`, `role`, and `student.grade` when role is student\n"
        "- **Update name/grade:** `PATCH /users/me` with `{ full_name?, grade?, prev_year_science_marks? }`\n"
        "- **Roles:** `student` | `teacher` (legacy `educator` accepted as teacher)\n"
        "- **JWT:** Bearer token, max 6h; use `GET /auth/session` to detect expiry\n\n"
        "Interactive docs: `/docs` (Swagger) · `/redoc`"
    ),
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
    contact={"name": "SCI-PATH"},
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(google_oauth.router)
app.include_router(users.router)
app.include_router(users.students_router)
app.include_router(classes.router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code >= 500:
        log.error(
            "http_error status=%s path=%s detail=%s",
            exc.status_code,
            request.url.path,
            exc.detail,
        )
    elif exc.status_code >= 400:
        log.warning(
            "http_error status=%s path=%s detail=%s",
            exc.status_code,
            request.url.path,
            exc.detail,
        )
    detail = exc.detail
    if isinstance(detail, dict) and "message" in detail:
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})
    if isinstance(detail, dict):
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": {
                "code": "http_error",
                "message": str(detail),
                "action": "login" if exc.status_code == 401 else "none",
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    log.warning("validation_error path=%s errors=%s", request.url.path, errors)
    # Pick a readable first message
    first = errors[0] if errors else {}
    loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    msg = first.get("msg") or "Invalid request"
    message = f"{loc}: {msg}" if loc else str(msg)
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "validation_error",
                "message": message,
                "action": "none",
                "errors": errors,
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("unhandled_error path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "server_error",
                "message": "Something went wrong. Please try again.",
                "action": "none",
            }
        },
    )


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=OPENAPI_TAGS,
        contact=app.contact,
    )
    schema["paths"] = {
        path: methods
        for path, methods in (schema.get("paths") or {}).items()
        if path in OPENAPI_INCLUDE_PATHS
    }
    used_tags = {
        tag
        for methods in schema["paths"].values()
        for op in methods.values()
        if isinstance(op, dict)
        for tag in (op.get("tags") or [])
        if isinstance(tag, str)
    }
    schema["tags"] = [t for t in OPENAPI_TAGS if t["name"] in used_tags]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["health"],
    summary="Health check",
)
def health() -> HealthResponse:
    db_kind = "postgresql" if settings.database_url.startswith("postgresql") else "sqlite"
    return HealthResponse(status="ok", service="user-management", database=db_kind)
