from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import (
    ExerciseDefinition,
    GymDay,
    LoggedExerciseResult,
    LoggedSession,
    Routine,
    User,
)
from app.schemas import ExerciseProgressPoint

router = APIRouter(tags=["exercises"])


@router.get(
    "/exercises/{exercise_definition_id}/progress",
    response_model=list[ExerciseProgressPoint],
)
def get_exercise_progress(
    exercise_definition_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    owns_exercise = (
        db.query(ExerciseDefinition.id)
        .join(GymDay, ExerciseDefinition.gym_day_id == GymDay.id)
        .join(Routine, GymDay.routine_id == Routine.id)
        .filter(ExerciseDefinition.id == exercise_definition_id, Routine.user_id == user.id)
        .one_or_none()
    )
    if owns_exercise is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Exercise not found")

    return exercise_progress(db, exercise_definition_id)


def exercise_progress(db: Session, exercise_definition_id: int) -> list[ExerciseProgressPoint]:
    """Every logged result for one exercise, oldest first. Caller checks ownership."""
    rows = (
        db.query(
            LoggedSession.logged_at,
            LoggedExerciseResult.weight_lb,
            LoggedExerciseResult.reps_done,
        )
        .join(LoggedExerciseResult, LoggedExerciseResult.session_id == LoggedSession.id)
        .filter(LoggedExerciseResult.exercise_definition_id == exercise_definition_id)
        .order_by(LoggedSession.logged_at.asc())
        .all()
    )
    return [
        ExerciseProgressPoint(logged_at=logged_at, weight_lb=weight_lb, reps_done=reps_done)
        for logged_at, weight_lb, reps_done in rows
    ]
