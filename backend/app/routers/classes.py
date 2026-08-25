from __future__ import annotations

import secrets
import string

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.errors import client_error
from app.models import ClassEnrollment, ClassRoom, User
from app.schemas import (
    ClassCreateRequest,
    ClassJoinRequest,
    ClassJoinResponse,
    ClassPublic,
    ClassRosterResponse,
)
from app.serializers import normalize_role

router = APIRouter(prefix="/classes", tags=["classes"])


def _require_teacher(user: User) -> None:
    if normalize_role(user.role) != "teacher":
        raise client_error(
            code="teacher_required",
            message="Only teachers can perform this action.",
            http_status=403,
        )


def _require_student(user: User) -> None:
    if normalize_role(user.role) != "student":
        raise client_error(
            code="student_required",
            message="Only students can perform this action.",
            http_status=403,
        )


def _class_for_owner(db: Session, class_code: str, teacher: User) -> ClassRoom:
    class_room = db.get(ClassRoom, class_code.strip().upper())
    if not class_room:
        raise client_error(
            code="class_not_found",
            message="Class not found.",
            http_status=404,
        )
    if class_room.teacher_id != teacher.id:
        raise client_error(
            code="class_access_denied",
            message="You can only access classes you own.",
            http_status=403,
        )
    return class_room


def _new_class_code(db: Session, grade: int) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        suffix = "".join(secrets.choice(alphabet) for _ in range(6))
        code = f"SCI-G{grade}-{suffix}"
        if db.get(ClassRoom, code) is None:
            return code
    raise client_error(
        code="class_code_generation_failed",
        message="Could not generate a unique class code. Please retry.",
        http_status=503,
    )


@router.post("", response_model=ClassPublic, status_code=201, summary="Create a class")
def create_class(
    body: ClassCreateRequest,
    teacher: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClassRoom:
    _require_teacher(teacher)
    class_room = ClassRoom(
        class_code=_new_class_code(db, body.grade_level),
        teacher_id=teacher.id,
        class_name=body.class_name.strip(),
        grade_level=body.grade_level,
        subject=body.subject.strip(),
    )
    db.add(class_room)
    db.commit()
    db.refresh(class_room)
    return class_room


@router.get("/mine", response_model=list[ClassPublic], summary="List my classes")
def list_my_classes(
    teacher: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ClassRoom]:
    _require_teacher(teacher)
    return (
        db.query(ClassRoom)
        .filter(ClassRoom.teacher_id == teacher.id)
        .order_by(ClassRoom.created_at.desc())
        .all()
    )


@router.get(
    "/enrolled",
    response_model=list[ClassPublic],
    summary="List classes I am enrolled in",
)
def list_enrolled_classes(
    learner_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ClassRoom]:
    """Student dashboard: classes joined via class code."""
    _require_student(learner_user)
    learner = learner_user.student_profile
    if not learner:
        return []

    codes = [
        row[0]
        for row in (
            db.query(ClassEnrollment.class_code)
            .filter(ClassEnrollment.learner_id == learner.learner_id)
            .order_by(ClassEnrollment.enrolled_at.desc())
            .all()
        )
    ]
    if not codes:
        return []

    rooms = (
        db.query(ClassRoom)
        .filter(ClassRoom.class_code.in_(codes), ClassRoom.is_active.is_(True))
        .all()
    )
    by_code = {room.class_code: room for room in rooms}
    # Preserve enrollment order (newest first).
    return [by_code[code] for code in codes if code in by_code]


@router.post("/join", response_model=ClassJoinResponse, summary="Join a class")
def join_class(
    body: ClassJoinRequest,
    learner_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClassJoinResponse:
    _require_student(learner_user)
    learner = learner_user.student_profile
    if not learner or learner.grade is None:
        raise client_error(
            code="learner_profile_missing",
            message="Your learner profile or grade is missing.",
            http_status=400,
        )

    code = body.class_code.strip().upper()
    class_room = db.get(ClassRoom, code)
    if not class_room or not class_room.is_active:
        raise client_error(
            code="class_not_found",
            message="That class code is invalid or inactive.",
            http_status=404,
        )
    if learner.grade != class_room.grade_level:
        raise client_error(
            code="class_grade_mismatch",
            message=f"This class is for Grade {class_room.grade_level}.",
            http_status=400,
        )

    existing = (
        db.query(ClassEnrollment)
        .filter(
            ClassEnrollment.class_code == code,
            ClassEnrollment.learner_id == learner.learner_id,
        )
        .first()
    )
    if not existing:
        db.add(ClassEnrollment(class_code=code, learner_id=learner.learner_id))
        db.commit()

    return ClassJoinResponse(
        message="Already enrolled." if existing else "Class joined successfully.",
        class_info=ClassPublic.model_validate(class_room),
    )


@router.get(
    "/{class_code}/roster",
    response_model=ClassRosterResponse,
    summary="Get roster for my class",
)
def get_class_roster(
    class_code: str,
    teacher: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClassRosterResponse:
    _require_teacher(teacher)
    class_room = _class_for_owner(db, class_code, teacher)
    learner_ids = [
        row[0]
        for row in (
            db.query(ClassEnrollment.learner_id)
            .filter(ClassEnrollment.class_code == class_room.class_code)
            .order_by(ClassEnrollment.enrolled_at)
            .all()
        )
    ]
    return ClassRosterResponse(
        class_code=class_room.class_code,
        class_name=class_room.class_name,
        grade_level=class_room.grade_level,
        learner_ids=learner_ids,
    )


@router.get("/{class_code}", response_model=ClassPublic, summary="Get my class metadata")
def get_class(
    class_code: str,
    teacher: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClassRoom:
    _require_teacher(teacher)
    return _class_for_owner(db, class_code, teacher)
