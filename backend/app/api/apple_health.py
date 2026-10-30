"""Dedicated upload credential; cookie authentication grants status access only."""

import hashlib
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.apple_health import AppleHealthSettings, enqueue, queue_status
from app.apple_health_fit import InvalidWorkout, normalize, to_fit
from app.auth import get_current_user
from app.models import User
from app.rate_limit import RateLimiter, client_ip, enforce

router = APIRouter(tags=["apple-health"])
limiter = RateLimiter(120, 60)
MAX_BODY = 16 * 1024 * 1024


def settings():
    try:
        return AppleHealthSettings.load()
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Apple Health connection needs configuration") from None


def prepare(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise InvalidWorkout("Expected Health Auto Export JSON data object")
    workouts = payload["data"].get("workouts")
    if not isinstance(workouts, list) or len(workouts) > 100:
        raise InvalidWorkout("Expected at most 100 workouts; enable Batch Requests")
    prepared = []
    skipped = 0
    for workout in workouts:
        normalized = normalize(workout)
        if normalized is None:
            skipped += 1
            continue
        canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        prepared.append((normalized["id"], hashlib.sha256(canonical.encode()).hexdigest(),
                         to_fit(normalized)))
    return prepared, skipped


@router.post("/integrations/apple-health/workouts", status_code=202)
async def receive(request: Request):
    cfg = settings()
    if cfg is None:
        raise HTTPException(404, "Apple Health connection is not configured")
    enforce(limiter, "apple-health:" + client_ip(request))
    if not cfg.authorized(request.headers.get("authorization")):
        raise HTTPException(401, "Invalid upload credential")
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise HTTPException(415, "Select JSON export format")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPException(415, "Compressed requests are not supported")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY:
            raise HTTPException(413, "Upload too large; enable batching or shorten date range")
        body.extend(chunk)
    try:
        prepared, skipped = await run_in_threadpool(prepare, json.loads(body))
    except InvalidWorkout as exc:
        raise HTTPException(422, str(exc)) from None
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise HTTPException(422, "Invalid version 2 workout export") from None
    try:
        result = await run_in_threadpool(enqueue, cfg, prepared)
    except (OSError, ValueError, sqlite3.Error):
        raise HTTPException(503, "Apple Health storage is unavailable; retry later") from None
    return {**result, "skipped_non_running": skipped,
            "note": "Stored for import. Check the training hub for Endurain completion."}


@router.get("/training/apple-health")
def status(user: User = Depends(get_current_user)):
    cfg = settings()
    if cfg is None:
        return {"configured": False, "counts": {}, "changed": 0, "recent": []}
    if user.username != cfg.owner:
        raise HTTPException(403, "Apple Health connection is not available for this profile")
    try:
        return queue_status(cfg)
    except (OSError, ValueError, sqlite3.Error):
        raise HTTPException(503, "Apple Health upload storage is unavailable") from None
