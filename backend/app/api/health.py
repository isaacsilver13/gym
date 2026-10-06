import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import load_settings
from app.db import get_db
from app.error_log import recent_errors
from app.models import LoggedSession

router = APIRouter(tags=["health"])


@router.get("/health/errors")
def health_errors(x_admin_token: str | None = Header(default=None)):
    # Fail closed: with no ADMIN_TOKEN configured the endpoint is unreachable.
    expected = load_settings().admin_token
    if not expected or not x_admin_token or not hmac.compare_digest(
        x_admin_token.encode(), expected.encode()
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return {"errors": recent_errors()}


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "healthy"}


@router.get("/health/metrics")
def health_metrics(db: Session = Depends(get_db)):
    last_session_at = db.query(func.max(LoggedSession.logged_at)).scalar()
    sessions_logged_total = db.query(func.count(LoggedSession.id)).scalar()
    return {
        "last_activity_at": last_session_at,
        "sessions_logged_total": sessions_logged_total,
    }
