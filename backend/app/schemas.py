from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


Role = Literal["student", "teacher"]


def _normalize_grades(v: list[int]) -> list[int]:
    out: list[int] = []
    for g in v:
        g = int(g)
        if g < 6 or g > 9:
            raise ValueError("grades must be 6–9")
        if g not in out:
            out.append(g)
    return out


class StudentSignupRequest(BaseModel):
    """Student details. class_code is optional for self-study learners."""

    full_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Student display name.",
        examples=["Aisha Perera"],
    )
    email: EmailStr = Field(..., examples=["aisha@school.lk"])
    password: str = Field(..., min_length=8, max_length=128)
    grade: int = Field(
        ...,
        ge=6,
        le=9,
        description="School grade (6–9).",
        examples=[7],
    )
    prev_year_science_marks: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Optional previous-year science marks (0–100).",
    )
    class_code: str | None = Field(
        default=None,
        min_length=6,
        max_length=32,
        description="Optional teacher-provided code. Omit for self-study.",
        examples=["SCI-G7-A4K9"],
    )


class TeacherSignupRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    grades_taught: list[int] = Field(default_factory=list)
    class_sections: list[str] = Field(default_factory=list)
    school_name: str | None = Field(
        default=None,
        max_length=255,
        description="School / institution name (stored on educator profile metadata).",
    )

    @field_validator("grades_taught")
    @classmethod
    def _grades(cls, v: list[int]) -> list[int]:
        return _normalize_grades(v)


# Backward-compatible alias (older clients used "educator")
EducatorSignupRequest = TeacherSignupRequest


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str | None = Field(
        default=None,
        description="Required when the account already has a password.",
    )
    new_password: str = Field(..., min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: "UserPublic"


class SessionStatusResponse(BaseModel):
    authenticated: bool
    code: str
    message: str
    action: Literal["login", "none"] = "none"
    expires_in: int | None = None
    user: "UserPublic | None" = None


class StudentProfilePublic(BaseModel):
    grade: int = Field(..., description="Student grade 6–9.", examples=[7])
    prev_year_science_marks: float | None = Field(
        default=None,
        description="Previous-year science marks if provided at signup/update.",
    )
    learner_id: str | None = Field(
        default=None,
        description="Canonical learner profile ID used by learning and analytics services.",
    )
    class_codes: list[str] = Field(
        default_factory=list,
        description="Class codes this learner is enrolled in (teacher-owned classrooms).",
    )
    class_code: str | None = Field(
        default=None,
        description="Primary / most recent class code (first entry of class_codes).",
    )


class TeacherProfilePublic(BaseModel):
    grades_taught: list[int] = Field(
        default_factory=list,
        description="Grades this teacher covers (6–9).",
    )
    class_sections: list[str] = Field(default_factory=list)
    school_name: str | None = Field(
        default=None,
        description="School / institution if provided at signup.",
    )


EducatorProfilePublic = TeacherProfilePublic


class UserPublic(BaseModel):
    """Full public user profile returned after auth and on /users/me."""

    id: str = Field(..., description="User UUID.")
    email: str
    full_name: str = Field(..., description="Display name.")
    role: Role = Field(..., description="student | teacher")
    auth_provider: str = "password"
    student: StudentProfilePublic | None = Field(
        default=None,
        description="Present when role=student — includes grade.",
    )
    teacher: TeacherProfilePublic | None = None
    # Alias for older clients
    educator: TeacherProfilePublic | None = None
    created_at: datetime | None = None

    # Convenience for other services / JWT consumers
    student_id: str | None = Field(
        default=None,
        description="Same as `id` when role=student; handy for LPE user_id.",
    )

    model_config = {"from_attributes": True}


class StudentSummary(BaseModel):
    """
    Lightweight public summary for other microservices
    (Learning Path Engine, question engine, analytics).
    """

    student_id: str = Field(
        ...,
        description="Student user id (UUID). Use as LPE `user_id`.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    full_name: str = Field(..., description="Student display name.", examples=["Aisha Perera"])
    grade: int = Field(..., description="Grade 6–9.", examples=[7], ge=6, le=9)


class StudentProfileUpdate(BaseModel):
    full_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Update display name.",
    )
    grade: int | None = Field(
        default=None,
        ge=6,
        le=9,
        description="Update grade (6–9).",
        examples=[8],
    )
    prev_year_science_marks: float | None = Field(default=None, ge=0, le=100)


class TeacherProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    grades_taught: list[int] | None = None
    class_sections: list[str] | None = None

    @field_validator("grades_taught")
    @classmethod
    def _grades(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return v
        return _normalize_grades(v)


EducatorProfileUpdate = TeacherProfileUpdate


class ClassCreateRequest(BaseModel):
    class_name: str = Field(..., min_length=1, max_length=255)
    grade_level: int = Field(..., ge=6, le=9)
    subject: str = Field(default="Science", min_length=1, max_length=64)


class ClassJoinRequest(BaseModel):
    class_code: str = Field(..., min_length=6, max_length=32)


class ClassPublic(BaseModel):
    class_code: str
    class_name: str
    grade_level: int
    subject: str
    teacher_id: str
    is_active: bool = True

    model_config = {"from_attributes": True}


class ClassJoinResponse(BaseModel):
    message: str
    class_info: ClassPublic


class ClassRosterResponse(BaseModel):
    class_code: str
    class_name: str
    grade_level: int
    learner_ids: list[str]


class MessageResponse(BaseModel):
    message: str
    code: str | None = None
    detail: Any | None = None
    # Dev/testing only when expose_reset_token=true
    reset_token: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    database: str


TokenResponse.model_rebuild()
SessionStatusResponse.model_rebuild()
