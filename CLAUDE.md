# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Workout routine builder and progress tracker: define N gym days per week, each with a fixed exercise list (muscle group, name, sets, rep range), then log weight/reps per session and chart progress over time.

## Stack

- Backend: FastAPI + SQLAlchemy 2.0 (sync) + Alembic, bcrypt + signed-cookie sessions (`itsdangerous`). SQLite for local dev, Postgres in production.
- Frontend: React + Vite + TypeScript, Recharts for progress charts.
- Deployment: a single Fly.io app (`aisaac-gym`) — the backend serves the built frontend as static files (see `FRONTEND_DIST`/catch-all route in `backend/app/main.py`), so API and frontend share one origin/port and there's no nginx or separate `-web` app.

## Commands

Backend (Python >=3.11, sources under `backend/`):
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
pytest -q                          # full suite (testpaths = backend/tests)
pytest backend/tests/test_x.py::test_name   # single test
ruff check backend
```

Frontend (from `frontend/`): `npm install`, `npm run dev`.

Env vars are documented in `.env.example`; `DATABASE_URL` defaults to a local SQLite file (switch to `postgresql+psycopg://...?sslmode=require` for Postgres), and `SESSION_SECRET` must be a real random value outside local dev.

## Architecture

- `backend/app/main.py` wires the FastAPI app; `backend/app/db.py` is the SQLAlchemy engine/session setup; `backend/app/models.py` and `schemas.py` hold ORM models and Pydantic schemas respectively (not split into per-domain packages — this is a small, flat backend, not a layered one like `NFL_Confidence`).
- `backend/app/auth.py` implements bcrypt password hashing plus signed httpOnly cookie sessions — there is no JWT/OAuth here.
- `backend/app/error_log.py` backs the `/health/errors` endpoint — check it before adding a separate error-tracking mechanism.
- All API routes live under `/api/v1`: auth (`/auth/register`, `/login`, `/logout`, `/me`), routines (`POST/GET /routines`, `GET/DELETE /routines/{id}`), session logging (`POST/GET /routines/{id}/sessions`), progress (`GET /exercises/{id}/progress`), and health (`/health`, `/health/ready`, `/health/metrics`, `/health/errors`).
- Deploys as a single Fly.io app built from `docker/Dockerfile` (a two-stage build: `npm run build` in `frontend/`, then the output is copied into the Python image as `frontend_dist/`). `alembic upgrade head` runs as the Fly `release_command` on every deploy, so a broken migration blocks deployment rather than shipping.
