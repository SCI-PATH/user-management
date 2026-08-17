from __future__ import annotations

import json
from typing import Any

from app.models import User
from app.schemas import StudentProfilePublic, TeacherProfilePublic, UserPublic


def normalize_role(role: str | None) -> str:
    """Canonical roles: student | teacher. Accept shared 'learner' and legacy 'educator'."""
    r = (role or "").strip().lower()
    if r in ("educator", "teacher"):
        return "teacher"
    if r in ("learner", "student"):
        return "student"
    return r or "student"


def is_teacher_role(role: str | None) -> bool:
    return normalize_role(role) == "teacher"


def _parse_grades(raw: str | None) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def _parse_sections(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _display_name(user: User) -> str:
    sp = user.student_profile
    if sp and sp.display_name:
        return sp.display_name
    return user.username or user.email or user.id


def user_to_public(user: User) -> UserPublic:
    role = normalize_role(user.role)
    student = None
    teacher = None
    if role == "student" and user.student_profile and user.student_profile.grade is not None:
        sp = user.student_profile
        student = StudentProfilePublic(
            grade=sp.grade,
            prev_year_science_marks=sp.prev_year_science_marks,
            learner_id=sp.learner_id,
        )
    if is_teacher_role(user.role) and user.educator_profile:
        ep = user.educator_profile
        teacher = TeacherProfilePublic(
            grades_taught=_parse_grades(ep.grades_taught),
            class_sections=_parse_sections(ep.class_sections),
        )
    return UserPublic(
        id=user.id,
        email=user.email or "",
        full_name=_display_name(user),
        role=role,  # type: ignore[arg-type]
        auth_provider=user.auth_provider or "password",
        student=student,
        teacher=teacher,
        educator=teacher,
        created_at=user.created_at,
        student_id=(
            user.student_profile.learner_id
            if role == "student" and user.student_profile
            else None
        ),
    )


def token_claims_for_user(user: User) -> dict[str, Any]:
    role = normalize_role(user.role)
    claims: dict[str, Any] = {
        "user_id": user.id,
        "role": role,
        "email": user.email or "",
        "full_name": _display_name(user),
    }
    if role == "student" and user.student_profile and user.student_profile.grade is not None:
        claims["grade"] = user.student_profile.grade
    if is_teacher_role(user.role) and user.educator_profile:
        claims["grades"] = _parse_grades(user.educator_profile.grades_taught)
        claims["sections"] = _parse_sections(user.educator_profile.class_sections)
    return claims


def dump_json(obj: Any) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj)
