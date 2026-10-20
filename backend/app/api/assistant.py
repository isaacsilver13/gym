import hmac
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.api.exercises import exercise_progress
from app.api.routines import routine_sessions
from app.config import load_settings
from app.db import get_db
from app.models import GymDay, Routine, User
from app.schemas import (
    AssistantExerciseOut,
    AssistantGymDayOut,
    AssistantSummaryOut,
    ExerciseProgressPoint,
)

router = APIRouter(prefix="/assistant", tags=["assistant"])

BEST_SET_WINDOW = timedelta(days=30)


def assistant_user(
    x_assistant_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    settings = load_settings()
    expected, username = settings.assistant_read_token, settings.assistant_username
    # Not configured = the feature does not exist.
    if not expected or not username:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
    if not x_assistant_token or not hmac.compare_digest(
        x_assistant_token.encode(), expected.encode()
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Forbidden")
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")
    return user


def _naive_utc(moment: datetime) -> datetime:
    # SQLite and Postgres "timestamp without time zone" both hand back naive UTC.
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


def _best_set(points: list[ExerciseProgressPoint]) -> ExerciseProgressPoint | None:
    cutoff = _naive_utc(datetime.now(UTC) - BEST_SET_WINDOW)
    recent = [p for p in points if _naive_utc(p.logged_at) >= cutoff]
    return max(recent, key=lambda p: (p.weight_lb, p.reps_done), default=None)


@router.get("/summary", response_model=AssistantSummaryOut)
def assistant_summary(user: User = Depends(assistant_user), db: Session = Depends(get_db)):
    routines = (
        db.query(Routine)
        .options(joinedload(Routine.gym_days).joinedload(GymDay.exercises))
        .filter(Routine.user_id == user.id)
        .order_by(Routine.created_at.desc(), Routine.id.desc())
        .all()
    )
    # Newest routine that has been trained, else the newest routine at all.
    routine, sessions = None, []
    for candidate in routines:
        sessions = routine_sessions(db, candidate)
        if sessions:
            routine = candidate
            break
    if routine is None and routines:
        routine = routines[0]
    if routine is None:
        return AssistantSummaryOut(
            username=user.username,
            routine=None,
            next_gym_day=None,
            last_session_date=None,
            exercises=[],
        )

    days = routine.gym_days  # ordered by order_index
    next_day = days[0]
    if sessions:
        last_index = next(i for i, day in enumerate(days) if day.id == sessions[0].gym_day_id)
        next_day = days[(last_index + 1) % len(days)]

    exercises = []
    for day in days:
        for exercise in day.exercises:
            points = exercise_progress(db, exercise.id)
            exercises.append(
                AssistantExerciseOut(
                    id=exercise.id,
                    name=exercise.name,
                    muscle_group=exercise.muscle_group,
                    gym_day=day.name,
                    latest=points[-1] if points else None,
                    best_30d=_best_set(points),
                )
            )

    return AssistantSummaryOut(
        username=user.username,
        routine=routine,
        next_gym_day=AssistantGymDayOut(id=next_day.id, name=next_day.name),
        last_session_date=sessions[0].logged_at.date() if sessions else None,
        exercises=exercises,
    )
