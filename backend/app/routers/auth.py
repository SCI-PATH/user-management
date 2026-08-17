from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.errors import auth_error, client_error
from app.models import ClassEnrollment, ClassRoom, EducatorProfile, StudentProfile, User
from app.schemas import (
    ChangePasswordRequest,
    EducatorSignupRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    SessionStatusResponse,
    StudentSignupRequest,
    TeacherSignupRequest,
    TokenResponse,
    UserPublic,
)
from app.security import (
    classify_token,
    consume_password_reset_token,
    create_access_token,
    create_password_reset_token,
    hash_password,
    is_token_revoked,
    revoke_token,
    verify_password,
)
from app.serializers import normalize_role, token_claims_for_user, user_to_public

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
bearer = HTTPBearer(auto_error=False)


def _issue_token(user: User) -> TokenResponse:
    claims = token_claims_for_user(user)
    public = user_to_public(user)
    token, exp, _jti = create_access_token(
        user_id=user.id,
        role=normalize_role(user.role),
        email=public.email,
        full_name=public.full_name,
        student_id=public.student_id,
        grade=claims.get("grade"),
        grades=claims.get("grades"),
        sections=claims.get("sections"),
    )
    expires_in = max(0, int((exp - datetime.utcnow()).total_seconds()))
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=public,
    )


@router.post(
    "/signup/student",
    response_model=TokenResponse,
    status_code=201,
    summary="Register student (name, grade, email, password)",
)
def signup_student(body: StudentSignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Register a learner and optionally enroll them in a matching class."""
    email = body.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise client_error(
            code="email_taken",
            message="An account with this email already exists.",
            http_status=409,
        )

    class_code = body.class_code.strip().upper() if body.class_code else None
    class_room = None
    if class_code:
        class_room = db.get(ClassRoom, class_code)
        if not class_room or not class_room.is_active:
            raise client_error(
                code="class_not_found",
                message="That class code is invalid or inactive.",
                http_status=404,
            )
        if class_room.grade_level != body.grade:
            raise client_error(
                code="class_grade_mismatch",
                message=(
                    f"This class is for Grade {class_room.grade_level}. "
                    f"Select Grade {class_room.grade_level} or continue without a class code."
                ),
                http_status=400,
            )

    name = body.full_name.strip()
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        username=name,
        role="learner",
    )
    user.auth_provider = "password"
    db.add(user)
    db.flush()
    learner = StudentProfile(
        learner_id=user.id,
        user_id=user.id,
        display_name=name,
        grade=body.grade,
        class_section=None,
    )
    db.add(learner)
    if class_room:
        db.add(ClassEnrollment(class_code=class_room.class_code, learner_id=learner.learner_id))
    # prev_year marks are not on shared.learners yet — ignored for persistence
    db.commit()
    db.refresh(user)
    return _issue_token(user)


def _signup_teacher(body: TeacherSignupRequest, db: Session) -> TokenResponse:
    email = body.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise client_error(
            code="email_taken",
            message="An account with this email already exists.",
            http_status=409,
        )

    name = body.full_name.strip()
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        username=name,
        role="teacher",
    )
    user.auth_provider = "password"
    db.add(user)
    db.flush()
    grades = ",".join(str(g) for g in body.grades_taught)
    sections = ",".join(s.strip() for s in body.class_sections if s and s.strip())
    db.add(
        EducatorProfile(
            user_id=user.id,
            grades_taught=grades,
            class_sections=sections,
        )
    )
    db.commit()
    db.refresh(user)
    return _issue_token(user)


@router.post(
    "/signup/teacher",
    response_model=TokenResponse,
    status_code=201,
    summary="Register teacher",
)
def signup_teacher(body: TeacherSignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Register a teacher with email + password."""
    return _signup_teacher(body, db)


@router.post(
    "/signup/educator",
    response_model=TokenResponse,
    status_code=201,
    summary="Register teacher (legacy alias)",
    deprecated=True,
)
def signup_educator(body: EducatorSignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Alias of /signup/teacher (legacy path)."""
    return _signup_teacher(body, db)


@router.post("/login", response_model=TokenResponse, summary="Email + password login")
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Email + password login (students and teachers)."""
    email = body.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise auth_error(
            code="invalid_credentials",
            message="Invalid email or password.",
            action="none",
        )
    if not user.password_hash:
        raise auth_error(
            code="password_not_set",
            message="This account uses Google sign-in. Use Google login, or set a password via forgot password.",
            action="none",
        )
    if not verify_password(body.password, user.password_hash):
        raise auth_error(
            code="invalid_credentials",
            message="Invalid email or password.",
            action="none",
        )
    if not user.is_active:
        raise auth_error(
            code="account_inactive",
            message="Account is inactive.",
            http_status=403,
            action="none",
        )
    if user.role == "educator":
        user.role = "teacher"
        db.commit()
        db.refresh(user)
    return _issue_token(user)


@router.post("/logout", response_model=MessageResponse, summary="Logout / revoke token")
def logout(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """End the current session. Frontend should clear the token and show login."""
    if not creds or not creds.credentials:
        return MessageResponse(message="Already signed out.", code="already_signed_out")
    status_kind, payload = classify_token(creds.credentials)
    if status_kind != "ok" or not payload:
        return MessageResponse(message="Already signed out.", code="already_signed_out")
    jti = payload.get("jti")
    sub = payload.get("sub") or ""
    exp = payload.get("exp")
    if jti and exp:
        expires_at = datetime.utcfromtimestamp(int(exp)) if not isinstance(exp, datetime) else exp
        try:
            revoke_token(db, jti=jti, user_id=sub, expires_at=expires_at)
        except Exception:
            pass
    return MessageResponse(message="Signed out. Please log in again.", code="logged_out")


@router.get("/session", response_model=SessionStatusResponse, summary="Check JWT session")
def session_status(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> SessionStatusResponse:
    """
    Check whether the current token is still valid.
    Frontend can poll this and redirect to login when action=login.
    """
    if not creds or not creds.credentials:
        return SessionStatusResponse(
            authenticated=False,
            code="not_authenticated",
            message="Please log in to continue.",
            action="login",
        )
    status_kind, payload = classify_token(creds.credentials)
    if status_kind == "expired":
        return SessionStatusResponse(
            authenticated=False,
            code="session_expired",
            message="Your session timed out. Please log in again.",
            action="login",
        )
    if status_kind != "ok" or not payload:
        return SessionStatusResponse(
            authenticated=False,
            code="invalid_token",
            message="Invalid session. Please log in again.",
            action="login",
        )
    if is_token_revoked(db, payload.get("jti")):
        return SessionStatusResponse(
            authenticated=False,
            code="logged_out",
            message="You have been signed out. Please log in again.",
            action="login",
        )
    user = db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        return SessionStatusResponse(
            authenticated=False,
            code="user_inactive",
            message="Account not found or inactive. Please log in again.",
            action="login",
        )
    exp = payload.get("exp")
    expires_in = None
    if exp is not None:
        try:
            exp_dt = datetime.utcfromtimestamp(int(exp)) if not isinstance(exp, datetime) else exp
            expires_in = max(0, int((exp_dt - datetime.utcnow()).total_seconds()))
        except Exception:
            expires_in = None
    return SessionStatusResponse(
        authenticated=True,
        code="ok",
        message="Session active.",
        action="none",
        expires_in=expires_in,
        user=user_to_public(user),
    )


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request password reset",
)
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)) -> MessageResponse:
    """
    Start password reset. Always returns a generic success message
    (does not reveal whether the email exists).
    """
    email = body.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()
    reset_token = None
    if user and user.is_active:
        # Google-only accounts can still set a password this way
        reset_token = create_password_reset_token(db, user.id)

    msg = MessageResponse(
        message="If an account exists for that email, a reset link is available. Check your email or use the reset token.",
        code="reset_requested",
    )
    if reset_token and settings.expose_reset_token:
        msg.reset_token = reset_token
        msg.detail = {
            "hint": "Dev mode: use reset_token with POST /auth/reset-password. Set EXPOSE_RESET_TOKEN=false in production.",
            "expires_minutes": settings.password_reset_expire_minutes,
        }
    return msg


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password with token",
)
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)) -> MessageResponse:
    """Complete forgot-password flow with the one-time token."""
    user_id = consume_password_reset_token(db, body.token)
    if not user_id:
        raise client_error(
            code="invalid_reset_token",
            message="Reset link is invalid or has expired. Request a new one.",
            http_status=400,
        )
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise client_error(
            code="user_inactive",
            message="Account not found or inactive.",
            http_status=400,
        )
    user.password_hash = hash_password(body.new_password)
    if user.auth_provider == "google":
        user.auth_provider = "password+google"
    elif not user.auth_provider:
        user.auth_provider = "password"
    db.commit()
    return MessageResponse(
        message="Password updated. Please log in with your new password.",
        code="password_reset",
    )


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change password (logged in)",
)
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Change password while logged in."""
    if user.password_hash:
        if not body.current_password:
            raise client_error(
                code="current_password_required",
                message="Current password is required.",
            )
        if not verify_password(body.current_password, user.password_hash):
            raise client_error(
                code="current_password_incorrect",
                message="Current password is incorrect.",
                http_status=400,
            )
    user.password_hash = hash_password(body.new_password)
    if user.auth_provider == "google":
        user.auth_provider = "password+google"
    db.commit()
    return MessageResponse(message="Password changed successfully.", code="password_changed")


@router.get(
    "/me",
    response_model=UserPublic,
    summary="Get my profile (alias of /users/me)",
)
def me(user: User = Depends(get_current_user)) -> UserPublic:
    return user_to_public(user)


@router.get("/google/status", summary="Is Google OAuth configured?")
def google_status() -> dict:
    configured = bool(settings.google_client_id and settings.google_client_secret)
    return {
        "enabled": configured,
        "register": configured,
        "login": configured,
        "message": (
            "Google OAuth ready for register and login"
            if configured
            else "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to enable Google register/login."
        ),
    }
