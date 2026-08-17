from __future__ import annotations

import urllib.parse
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import EducatorProfile, StudentProfile, User
from app.security import create_access_token
from app.serializers import normalize_role, token_claims_for_user, user_to_public

router = APIRouter(prefix="/auth/google", tags=["auth-google"])
settings = get_settings()


def _normalize_role_param(role: str) -> str:
    r = (role or "student").strip().lower()
    if r in ("educator", "teacher"):
        return "teacher"
    if r == "student":
        return "student"
    raise HTTPException(status_code=400, detail="role must be student or teacher")


def _oauth_error_redirect(message: str) -> RedirectResponse:
    dest = settings.oauth_success_redirect.rstrip("/")
    q = urllib.parse.urlencode({"error": message})
    return RedirectResponse(f"{dest}?{q}")


@router.get(
    "/start",
    summary="Start Google OAuth",
    response_description="302 redirect to Google consent screen.",
)
def google_start(
    role: str = Query(default="student", description="student | teacher (for register)"),
    mode: str = Query(
        default="auto",
        description="register = create if new; login = existing accounts only; auto = login or register",
    ),
):
    """
    Start Google OAuth for register or login.

    - mode=register&role=student|teacher → create account if new
    - mode=login → sign in only (fails if no account)
    - mode=auto → login if exists, else register with role
    """
    mode_n = (mode or "auto").strip().lower()
    if mode_n not in ("auto", "login", "register"):
        raise HTTPException(status_code=400, detail="mode must be auto, login, or register")
    role_n = _normalize_role_param(role) if mode_n != "login" else "student"
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not configured. Use email/password signup for now.",
        )
    # state encodes mode + role for the callback
    state = f"{mode_n}:{role_n}"
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return RedirectResponse(url)


@router.get("/callback", summary="Google OAuth callback", include_in_schema=True)
async def google_callback(
    code: str | None = None,
    state: str = "auto:student",
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        return _oauth_error_redirect(f"Google OAuth error: {error}")
    if not code:
        return _oauth_error_redirect("Missing authorization code")
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")

    # Parse state: "mode:role" or legacy bare "student"/"educator"/"teacher"
    mode_n = "auto"
    role_n = "student"
    if ":" in (state or ""):
        parts = state.split(":", 1)
        mode_n = (parts[0] or "auto").lower()
        try:
            role_n = _normalize_role_param(parts[1] if len(parts) > 1 else "student")
        except HTTPException:
            role_n = "student"
    else:
        try:
            role_n = _normalize_role_param(state or "student")
        except HTTPException:
            role_n = "student"

    async with httpx.AsyncClient(timeout=20.0) as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_res.status_code >= 400:
            return _oauth_error_redirect("Could not exchange Google code")
        tokens = token_res.json()
        access = tokens.get("access_token")
        if not access:
            return _oauth_error_redirect("Google did not return access token")

        info_res = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access}"},
        )
        if info_res.status_code >= 400:
            return _oauth_error_redirect("Could not load Google profile")
        info = info_res.json()

    email = (info.get("email") or "").lower().strip()
    sub = info.get("sub")
    name = (info.get("name") or email.split("@")[0] or "Learner").strip()
    if not email or not sub:
        return _oauth_error_redirect("Google account missing email")

    # google_sub is not stored on shared.users yet — match by email only
    user = db.query(User).filter(User.email == email).first()
    if user:
        user.google_sub = sub
        if user.auth_provider != "password":
            user.auth_provider = "google"
        else:
            user.auth_provider = "password+google"
        if user.role == "educator":
            user.role = "teacher"
        db.commit()
        db.refresh(user)
    else:
        if mode_n == "login":
            return _oauth_error_redirect("No account found. Please register first.")
        # register or auto → create
        db_role = "learner" if role_n == "student" else "teacher"
        user = User(
            email=email,
            password_hash=None,
            username=name,
            role=db_role,
        )
        user.auth_provider = "google"
        user.google_sub = sub
        db.add(user)
        db.flush()
        if role_n == "student":
            db.add(
                StudentProfile(
                    learner_id=user.id,
                    user_id=user.id,
                    display_name=name,
                    grade=7,
                    class_section=None,
                )
            )
        else:
            db.add(EducatorProfile(user_id=user.id, grades_taught="7", class_sections=""))
        db.commit()
        db.refresh(user)

    public = user_to_public(user)
    claims = token_claims_for_user(user)
    token, exp, _ = create_access_token(
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
    dest = settings.oauth_success_redirect.rstrip("/")
    q = urllib.parse.urlencode({"access_token": token, "expires_in": str(expires_in)})
    return RedirectResponse(f"{dest}?{q}")
