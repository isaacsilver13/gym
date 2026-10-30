"""Authenticated training hub; integration credentials stay on the server."""

from datetime import date
from zoneinfo import ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.assistant import assistant_user
from app.auth import get_current_user
from app.db import get_db
from app.migration import export_legacy
from app.models import User
from app.training import TrainingSettings, build_summary

router = APIRouter(tags=["training"])


@router.get("/training/legacy-export")
def legacy_export(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return export_legacy(db, user)


def _summary(user: User, anchor: date | None):
    cfg = TrainingSettings.load()
    if not cfg.username:
        raise HTTPException(404, "Training integration is not configured")
    if user.username != cfg.username:
        raise HTTPException(403, "Training integration is not available for this profile")
    try:
        return build_summary(cfg, anchor)
    except ZoneInfoNotFoundError:
        raise HTTPException(503, "Training timezone is not configured correctly") from None


@router.get("/training/summary")
def training_summary(anchor: date | None = None, user: User = Depends(get_current_user)):
    return _summary(user, anchor)


@router.get("/assistant/training")
def assistant_training(anchor: date | None = None, user: User = Depends(assistant_user)):
    return _summary(user, anchor)
