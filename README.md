# Gym Tracker

A personal workout tracker with routine building, session logging, and progress charts. An optional **openGym + Endurain training hub** adds a combined view of lifting and running, with Apple Health running-workout imports.
See [setup, migration, Apple Watch imports, and recovery](docs/training-integration.md).

The built-in tracker records weight and reps per exercise per session. The training hub integrates separate upstream applications; configuring those connections is optional and requires their own setup.

## Stack

- **Backend**: FastAPI + SQLAlchemy 2.0 (sync) + Alembic, bcrypt + signed-cookie sessions. SQLite for local dev, Postgres in production.
- **Frontend**: React + Vite + TypeScript, Recharts for progress charts.
- **Deployment**: One Fly.io app (`aisaac-gym`, https://aisaac-gym.fly.dev): the backend serves the built frontend, so API and SPA share one origin.

## Local development

```powershell
# Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
python -m uvicorn app.main:app --app-dir backend --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Run tests with `pytest -q`; lint with `ruff check backend`.

## Environment variables

See `.env.example`. `DATABASE_URL` defaults to a local SQLite file; set it to a Postgres URL (`postgresql+psycopg://...?sslmode=require`) in production. `SESSION_SECRET` must be a random value of 32+ characters outside local dev (the app refuses to start otherwise; set it with `fly secrets set`). Changing it signs everyone out. Login/register are rate limited per client (in-process, so per Fly machine). `/health/errors` requires an `X-Admin-Token` header matching `ADMIN_TOKEN` (disabled when unset).

## API

All routes are under `/api/v1`. Auth is a signed httpOnly cookie (`/auth/register`, `/auth/login`, `/auth/logout`, `/auth/me`). Routines: `POST/GET /routines`, `GET/DELETE /routines/{id}`. Logging: `POST /routines/{id}/sessions`, `GET /routines/{id}/sessions`. Progress: `GET /exercises/{id}/progress`. Health: `/health`, `/health/ready`, `/health/metrics`, `/health/errors`.
Assistant: `GET /assistant/summary` returns one user's current routine, next gym day, and latest / best-in-30-days set per exercise; it takes an `X-Assistant-Token` header instead of a cookie and returns 404 unless `ASSISTANT_READ_TOKEN` and `ASSISTANT_USERNAME` are set.


Login/registration limits are process-local and bounded; use shared storage before
scaling beyond one process. `TRUST_FLY_CLIENT_IP=true` is set only by the Fly
configuration; it is honored only in production with `FLY_APP_NAME` present and
assumes all HTTP ingress uses Fly Proxy. Leave it false for direct/self-hosted
ingress. Arbitrary local forwarding headers never select a limiter bucket.
