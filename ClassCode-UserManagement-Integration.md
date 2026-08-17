# Class Code & Classroom Scoping — Integration Guide

**Audience:** User Management / Authentication component owner  
**Consumer:** Component 4 — Learner Profile Analytics & GenAI Support (Liyaudeen D.H.)  
**Status:** Design contract (not yet implemented in Component 4 dashboard)

This document explains how **class codes** tie learners to teachers, what **your component** should build first, and what **Component 4** will consume afterward.

---

## 1. Problem we are solving

Today the teacher dashboard is a **manual demo**:

- Teacher pastes student IDs (`user_001`, …) into a text box.
- Topic columns include **all grades G6–G9** (~128 skills).
- **Anyone** who knows the API URL can query any student.

For production / research demo with real classes:

- A **Grade 7 teacher** opens the dashboard and sees **only her Section A learners**.
- Matrix columns are **only Grade 7 topics**, not the full G6–G9 grid.
- Learners join via a **class code** (Google Classroom style).

**BKT, at-risk logic, and Component 4 event tables do not change.**  
We only add **roster + grade scoping** on top.

---

## 2. Schema layout (Neon Postgres)

Your platform already uses a **`shared`** schema for cross-component data. Classroom tables belong there too.

```
shared                          learner_analytics (Component 4)
├── users          (auth)       ├── assessment_attempts
├── learners       (profiles)  ├── bkt_mastery
├── topics         (curriculum)├── bkt_skill_params
├── classes        ← NEW       ├── tutor_turns
└── class_enrollments ← NEW    └── frustration_cues
```

| Schema | Tables | Owner |
|--------|--------|-------|
| **`shared`** | `users`, `learners`, `topics`, **`classes`**, **`class_enrollments`** | User Management (+ curriculum seed for `topics`) |
| **`learner_analytics`** | attempt / mastery / tutor / engagement events | Component 4 |

**Do not duplicate `users` or `learners` in `learner_analytics`.**  
Use `shared.learners` as the platform roster; Component 4 writes events keyed by `learner_id`.

---

## 3. End-to-end flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│ PHASE A — User Management / Auth (your component)                        │
├──────────────────────────────────────────────────────────────────────────┤
│ 1. Teacher signs up → shared.users (role = 'teacher')                    │
│ 2. Teacher creates class → shared.classes (auto class_code SCI-G7-492)   │
│ 3. Teacher shares class_code with learners                               │
│ 4. Learner signs up → shared.users (role = 'learner')                    │
│    + shared.learners row (learner_id, account_user_id, grade_level)        │
│ 5. Learner joins with class_code → shared.class_enrollments row            │
│    • Validate learner.grade_level = classes.grade_level                  │
│ 6. Optional self-study: learner account without enrollment still works    │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ PHASE B — Learning activity (Components 2, 3, 4 — unchanged)             │
├──────────────────────────────────────────────────────────────────────────┤
│ POST /api/v1/assessment-submit  { user_id, topic_id, is_correct, ... }   │
│ POST /api/v1/engagement/frustration-cue                                    │
│ POST /tutor/hint                                                           │
│                                                                            │
│ Events stored in learner_analytics.* keyed by learner_id (= user_id).    │
│ Class code is NOT sent on these calls.                                     │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ PHASE C — Teacher dashboard (Component 4 — after your tables exist)        │
├──────────────────────────────────────────────────────────────────────────┤
│ POST /api/v1/mastery/matrix { "class_code": "SCI-G7-492" }                 │
│   1. Roster: SELECT learner_id FROM shared.class_enrollments               │
│   2. Grade:  SELECT grade_level FROM shared.classes                        │
│   3. Topics: SELECT topic_id FROM shared.topics WHERE grade = 7            │
│   4. Run existing matrix / at-risk on that slice                           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Canonical ID rules

### 4.1 Existing `shared` tables (your DDL)

**`shared.users`**

| Column | Notes |
|--------|-------|
| `user_id` | Login account PK |
| `role` | `'learner'` \| `'teacher'` |
| `username` | Unique login name |

**`shared.learners`**

| Column | Notes |
|--------|-------|
| `learner_id` | Profile PK — **this is what analytics APIs use** |
| `account_user_id` | FK → `shared.users.user_id` (nullable) |
| `grade_level` | 6–9 |
| `class_section` | Legacy/free-text; **prefer `class_enrollments` for roster** |

**`shared.topics`**

| Column | Notes |
|--------|-------|
| `topic_id` | e.g. `G7_BIO_01` — shared across all components |
| `grade` | 6–9 — use this to scope dashboard columns |

### 4.2 Recommended ID convention

For simplest integration across Components 2–4:

```text
learner_id = account_user_id = user_id   (e.g. all are "user_001")
```

Component 4 API payloads use `user_id`; internally that value should match `shared.learners.learner_id` and `learner_analytics.*.learner_id`.

If you ever split `learner_id` ≠ `account_user_id`, roster APIs must return **`learner_id`** (not only `account_user_id`), and Component 4 will join through `shared.learners`.

### 4.3 New tables (ALREADY added)

**`shared.classes`**

| Column | Type | Notes |
|--------|------|-------|
| `class_code` | VARCHAR(32) PK | Shareable join code, e.g. `SCI-G7-492` |
| `teacher_id` | FK → `shared.users` | Must be a user with `role = 'teacher'` |
| `class_name` | VARCHAR(255) | Display name |
| `grade_level` | INT2 | 6–9 |
| `subject` | VARCHAR(64) | Default `'Science'` |
| `is_active` | BOOLEAN | Soft-disable old classes |

**`shared.class_enrollments`**

| Column | Type | Notes |
|--------|------|-------|
| `enrollment_id` | BIGSERIAL PK | |
| `class_code` | FK → `shared.classes` | |
| `learner_id` | FK → `shared.learners` | |
| `enrolled_at` | TIMESTAMPTZ | |
| UNIQUE | `(class_code, learner_id)` | One row per learner per class |

---

## 5. Class code rules

| Rule | Recommendation |
|------|----------------|
| Format | Short, human-shareable: `SCI-G7-492` |
| Uniqueness | Globally unique `class_code` (PRIMARY KEY) |
| Grade match | On join, reject if `learners.grade_level != classes.grade_level` |
| Multiple classes | Learner may enroll in multiple classes (optional) |
| Teacher multiple classes | One teacher can own many classes (dashboard dropdown) |
| `class_section` column | Optional denormalized label on join; **`class_enrollments` is source of truth** |

---

## 6. APIs — split of responsibility

### 6.1 Your component (User Management - Dhanushi) — build these first

| Method | Endpoint (example) | Purpose |
|--------|-------------------|---------|
| POST | `/auth/signup` | Register teacher or learner |
| POST | `/classes` | Teacher creates class → returns `class_code` |
| GET | `/classes/mine` | List classes for logged-in teacher |
| POST | `/classes/join` | Learner joins with `{ class_code }` |
| GET | `/classes/{class_code}/roster` | `{ learner_ids, grade_level, class_name }` |
| GET | `/classes/{class_code}` | Metadata for dashboard header + copy button |

**Auth:** Verify `classes.teacher_id = current_user.user_id` before returning roster.

**On learner signup:**

1. Insert `shared.users` (`role = 'learner'`).
2. Insert `shared.learners` (`learner_id`, `account_user_id`, `display_name`, `grade_level`).

**On successful class join:**

1. Insert `shared.class_enrollments`.
2. Optionally update `shared.learners.class_section` for display (not required for analytics).



---

## 7. Example API payloads

### Teacher creates class

```json
POST /classes
Authorization: Bearer <teacher_jwt>

{
  "class_name": "Grade 7 Science - Section A",
  "grade_level": 7,
  "subject": "Science"
}
```

Response:

```json
{
  "class_code": "SCI-G7-492",
  "class_name": "Grade 7 Science - Section A",
  "grade_level": 7,
  "teacher_id": "user_teacher_99"
}
```

### Learner joins class

```json
POST /classes/join
Authorization: Bearer <learner_jwt>

{
  "class_code": "SCI-G7-492"
}
```

Backend validates `shared.learners.grade_level` matches `shared.classes.grade_level`.

### Roster API (for Component 4 or direct DB read)

```json
GET /classes/SCI-G7-492/roster

{
  "class_code": "SCI-G7-492",
  "class_name": "Grade 7 Science - Section A",
  "grade_level": 7,
  "learner_ids": ["user_001", "user_002", "user_003"]
}
```

### Teacher dashboard — matrix (Component 4 — future)

```json
POST /api/v1/mastery/matrix
Authorization: Bearer <teacher_jwt>

{
  "class_code": "SCI-G7-492"
}
```

---


---

## 10. Security checklist

- [ ] Teacher can only query roster for classes where `teacher_id = self`
- [ ] Learner cannot call matrix/at-risk for other classes
- [ ] `class_code` is hard enough to guess (e.g. 6+ chars)
- [ ] Rate-limit `/classes/join`
- [ ] Validate grade on join

---

