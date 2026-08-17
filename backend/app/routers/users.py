from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.errors import client_error
from app.models import EducatorProfile, StudentProfile, User
from app.schemas import (
    StudentProfileUpdate,
    StudentSummary,
    TeacherProfileUpdate,
    UserPublic,
)
from app.serializers import is_teacher_role, normalize_role, user_to_public

router = APIRouter(prefix="/users", tags=["users"])
students_router = APIRouter(prefix="/students", tags=["students"])


@router.get(
    "/me",
    response_model=UserPublic,
    summary="Get my profile (name, grade, role)",
    response_description="Authenticated user including student.grade when role=student.",
)
def get_me(user: User = Depends(get_current_user)) -> UserPublic:
    """Return the caller's public profile (JWT required)."""
    return user_to_public(user)


@router.patch(
    "/me",
    response_model=UserPublic,
    summary="Update my name / grade / marks",
)
async def update_me(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPublic:
    """Update profile. Students can update name, grade, and last-year marks."""
    try:
        raw = await request.json()
    except Exception as exc:
        raise client_error(code="invalid_json", message="Expected a JSON body.") from exc
    if not isinstance(raw, dict):
        raise client_error(code="invalid_json", message="Expected a JSON object.")

    role = normalize_role(user.role)
    if role == "student":
        try:
            body = StudentProfileUpdate(
                **{k: v for k, v in raw.items() if k in StudentProfileUpdate.model_fields}
            )
        except Exception as exc:
            raise client_error(code="validation_error", message=str(exc)) from exc
        data = body.model_dump(exclude_unset=True)
        if "full_name" in data and data["full_name"]:
            name = data["full_name"].strip()
            user.username = name
            if sp := user.student_profile:
                sp.display_name = name
        sp = user.student_profile
        if not sp:
            sp = StudentProfile(
                learner_id=user.id,
                user_id=user.id,
                display_name=user.username,
                grade=data.get("grade") or 7,
                class_section=None,
            )
            db.add(sp)
        if "grade" in data and data["grade"] is not None:
            sp.grade = data["grade"]
        if "prev_year_science_marks" in data:
            # Not on shared.learners — keep in-memory only for this request response
            sp.prev_year_science_marks = data["prev_year_science_marks"]
        # class_section is intentionally unused
        sp.class_section = None
    elif is_teacher_role(user.role):
        try:
            body = TeacherProfileUpdate(
                **{k: v for k, v in raw.items() if k in TeacherProfileUpdate.model_fields}
            )
        except Exception as exc:
            raise client_error(code="validation_error", message=str(exc)) from exc
        data = body.model_dump(exclude_unset=True)
        if "full_name" in data and data["full_name"]:
            user.username = data["full_name"].strip()
        ep = user.educator_profile
        if not ep:
            ep = EducatorProfile(user_id=user.id)
            db.add(ep)
        if "grades_taught" in data and data["grades_taught"] is not None:
            ep.grades_taught = ",".join(str(g) for g in data["grades_taught"])
        if "class_sections" in data and data["class_sections"] is not None:
            ep.class_sections = ",".join(s.strip() for s in data["class_sections"] if s and s.strip())
        if user.role == "educator":
            user.role = "teacher"
    else:
        raise client_error(code="unknown_role", message="Unknown role.")

    db.commit()
    db.refresh(user)
    return user_to_public(user)


@router.get(
    "/{user_id}",
    response_model=UserPublic,
    summary="Get user by id",
)
def get_user(user_id: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserPublic:
    u = db.get(User, user_id)
    if not u:
        raise client_error(code="user_not_found", message="User not found.", http_status=404)
    return user_to_public(u)


@students_router.get(
    "/{student_id}",
    response_model=StudentSummary,
    summary="Expose student name + grade",
    response_description="`{ student_id, full_name, grade }` for LPE / analytics / question engine.",
)
def get_student_summary(student_id: str, db: Session = Depends(get_db)) -> StudentSummary:
    """
    Expose student **name** + **grade** for other services (LPE, question engine, analytics).

    Does not return email or password. No JWT required (service-to-service).
    """
    sp = db.get(StudentProfile, student_id)
    if not sp:
        sp = db.query(StudentProfile).filter(StudentProfile.user_id == student_id).first()
    u = sp.user if sp else None
    if not u or normalize_role(u.role) != "student":
        raise client_error(code="student_not_found", message="Student not found.", http_status=404)
    if not sp or sp.grade is None:
        raise client_error(code="student_profile_missing", message="Student profile not found.", http_status=404)
    return StudentSummary(
        student_id=sp.learner_id,
        full_name=(sp.display_name or u.username or u.email or u.id),
        grade=sp.grade,
    )
