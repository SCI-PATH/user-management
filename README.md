# SCI-PATH · User Management Service

Standalone **auth & user profiles** microservice (outside `learning-path-engine`).

| Piece | Tech |
|-------|------|
| API | FastAPI on **:8001** |
| DB | Neon PostgreSQL (`shared.users`, `shared.learners`, classroom tables) |
| Auth | Email/password + optional **Google OAuth** |
| JWT | HS256, **max 6 hours**, logout via jti blocklist |
| UI | Shared `frontend-app` Next.js application |

---

## Folder layout

```text
user-management/
  backend/          # FastAPI
  ClassCode-UserManagement-Integration.md
  README.md
```

---

## Quick start (Windows)

### 1) Backend

```powershell
cd D:\dev\RP\user-management\backend
py -3.12 -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

- Docs: http://127.0.0.1:8001/docs  
- Health: http://127.0.0.1:8001/health  

The login/signup UI lives in `D:\dev\RP\frontend-app`. Its `/user-api`
rewrite forwards requests to this service on port 8001.

---

## Neon PostgreSQL

Set the team Neon connection in `backend/.env`:

```env
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST/neondb?sslmode=require
JWT_SECRET=use-a-long-random-secret
```

Accounts and learner profiles use `shared.users` and `shared.learners`.
Classroom membership uses `shared.classes` and `shared.class_enrollments`.

---

## API summary

| Method | Path | Notes |
|--------|------|--------|
| POST | `/auth/signup/student` | register; optional `class_code` for enrollment |
| POST | `/auth/signup/teacher` | email/password teacher register |
| POST | `/auth/signup/educator` | alias of `/signup/teacher` |
| POST | `/auth/login` | email/password login → JWT (≤ 6h) |
| POST | `/auth/logout` | Bearer token → revokes jti → back to login |
| GET | `/auth/session` | check timeout; `action=login` when expired |
| POST | `/auth/forgot-password` | request reset (dev may return `reset_token`) |
| POST | `/auth/reset-password` | `{ token, new_password }` |
| POST | `/auth/change-password` | logged-in change (`current_password`, `new_password`) |
| GET | `/auth/me` | current user (Bearer) |
| PATCH | `/users/me` | update name / grade / marks (students) |
| GET | `/users/{id}` | full profile (authenticated) |
| GET | `/students/{student_id}` | **name + grade** for other services |
| POST | `/classes` | teacher creates class and receives a code |
| GET | `/classes/mine` | teacher lists owned classes |
| POST | `/classes/join` | learner joins; validates matching grade |
| GET | `/classes/{class_code}` | teacher-owned class metadata |
| GET | `/classes/{class_code}/roster` | teacher-owned canonical learner IDs |
| GET | `/auth/google/start?mode=register\|login\|auto&role=student\|teacher` | Google OAuth |
| GET | `/auth/google/callback` | OAuth redirect |
| GET | `/auth/google/status` | whether Google is enabled |

### JWT claims (other services must accept these)

```json
{
  "sub": "<user uuid>",
  "student_id": "<same as sub for students>",
  "role": "student | teacher",
  "email": "...",
  "name": "...",
  "grade": 7,
  "grades": [7, 8],
  "sections": ["7-A"],
  "jti": "...",
  "exp": "..."
}
```

**Shared secret:** set the same `JWT_SECRET` in learning-path-engine when you wire verification later.

---

## Student signup fields

- Full name  
- Email + password  
- Current grade (6–9)  
- Optional previous year science final marks (%)  

(No class section.)

## Teacher signup fields

- Full name  
- Email + password  
- Grades taught (G6–G9 multi)  
- Class sections (optional list)  

## Sessions / timeout / logout

- Access token lifetime: **≤ 360 minutes (6 hours)**  
- On expiry, APIs return `401` with `detail.code = session_expired` and `detail.action = login`  
- `GET /auth/session` lets the UI poll and redirect to login  
- `POST /auth/logout` revokes the token  

## Forgot / change password

```http
POST /auth/forgot-password   { "email": "..." }
POST /auth/reset-password    { "token": "...", "new_password": "..." }
POST /auth/change-password   { "current_password": "...", "new_password": "..." }
```

With `EXPOSE_RESET_TOKEN=true` (local default), forgot-password returns `reset_token` for testing without email.
---

## Frontend: `useUser()`

```jsx
import { useUser } from "./auth/UserProvider.jsx";

function Example() {
  const { user, studentId, grade, isStudent, login, logout, loading } = useUser();
  // ...
}
```

After login, students land on a **Realm hub**; educators land on **section select + class overview** placeholders (metrics wire to analytics later).

Link to Learning Path Engine: `NEXT_PUBLIC_LPE_URL` (default `http://localhost:3000`).

---

## Google OAuth setup

1. Google Cloud Console → OAuth client (web).  
2. Authorized redirect: `http://127.0.0.1:8001/auth/google/callback`  
3. Set in `backend/.env`:

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://127.0.0.1:8001/auth/google/callback
OAUTH_SUCCESS_REDIRECT=http://127.0.0.1:3001/auth/callback
```

Register: `/auth/google/start?mode=register&role=student` (or `teacher`)  
Login: `/auth/google/start?mode=login`  

---

## Student name + grade API

Other services can call:

```http
GET /students/{student_id}
```

Response:

```json
{
  "student_id": "...",
  "full_name": "Ada",
  "grade": 7,
  "class_section": "7-A"
}
```

No email/password is returned.
---

## Integration with learning-path-engine (next step)

Not wired yet by design. When ready:

1. Copy JWT verify helper into LPE (same `JWT_SECRET`).  
2. Replace demo `user_id` with JWT `sub` / `student_id`.  
3. Prefer JWT `grade` for content.  
4. Protect teacher routes with `role === educator`.  

---

## Default ports

| Service | Port |
|---------|------|
| user-management API | 8001 |
| user-management UI | 3001 |
| learning-path-engine API | 8000 |
| learning-path-engine UI | 3000 |

## CI

Pushes to `main` or `dev` trigger a Docker build for this service in [deployment-orchestration](https://github.com/SCI-PATH/deployment-orchestration) via `trigger-orchestration.yml`. Requires `ORCHESTRATION_DISPATCH_TOKEN` on this repo and `SUBMODULES_ACCESS_TOKEN` on orchestration (same PAT value is fine).

Pipeline test: verify `sci-path-deploy` builds **um** only on push.
