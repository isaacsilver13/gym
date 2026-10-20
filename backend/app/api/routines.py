from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

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
from app.schemas import (
    LoggedSessionOut,
    LogSessionIn,
    RoutineIn,
    RoutineOut,
    RoutineSummary,
)

router = APIRouter(tags=["routines"])


def _get_owned_routine(db: Session, user: User, routine_id: int) -> Routine:
    routine = (
        db.query(Routine)
        .options(joinedload(Routine.gym_days).joinedload(GymDay.exercises))
        .filter(Routine.id == routine_id, Routine.user_id == user.id)
        .one_or_none()
    )
    if routine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Routine not found")
    return routine


@router.post("/routines", response_model=RoutineOut, status_code=status.HTTP_201_CREATED)
def create_routine(
    payload: RoutineIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    routine = Routine(user_id=user.id, name=payload.name)
    for day_index, day_in in enumerate(payload.gym_days):
        gym_day = GymDay(name=day_in.name, order_index=day_index)
        for exercise_index, exercise_in in enumerate(day_in.exercises):
            gym_day.exercises.append(
                ExerciseDefinition(order_index=exercise_index, **exercise_in.model_dump())
            )
        routine.gym_days.append(gym_day)
    db.add(routine)
    db.commit()
    db.refresh(routine)
    return routine


@router.get("/routines", response_model=list[RoutineSummary])
def list_routines(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(Routine)
        .filter(Routine.user_id == user.id)
        .order_by(Routine.created_at.desc())
        .all()
    )


@router.get("/routines/{routine_id}", response_model=RoutineOut)
def get_routine(
    routine_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return _get_owned_routine(db, user, routine_id)


@router.delete("/routines/{routine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_routine(
    routine_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    routine = _get_owned_routine(db, user, routine_id)
    db.delete(routine)
    db.commit()


@router.post(
    "/routines/{routine_id}/sessions",
    response_model=LoggedSessionOut,
    status_code=status.HTTP_201_CREATED,
)
def log_session(
    routine_id: int,
    payload: LogSessionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    routine = _get_owned_routine(db, user, routine_id)
    gym_day = next((day for day in routine.gym_days if day.id == payload.gym_day_id), None)
    if gym_day is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Gym day not found on this routine")

    valid_exercise_ids = {exercise.id for exercise in gym_day.exercises}
    for result in payload.results:
        if result.exercise_definition_id not in valid_exercise_ids:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Exercise {result.exercise_definition_id} is not part of this gym day",
            )

    session = LoggedSession(gym_day_id=gym_day.id)
    for result in payload.results:
        session.results.append(
            LoggedExerciseResult(
                exercise_definition_id=result.exercise_definition_id,
                weight_lb=result.weight_lb,
                reps_done=result.reps_done,
            )
        )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/routines/{routine_id}/sessions", response_model=list[LoggedSessionOut])
def list_sessions(
    routine_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return routine_sessions(db, _get_owned_routine(db, user, routine_id))


def routine_sessions(db: Session, routine: Routine) -> list[LoggedSession]:
    """All sessions logged against a routine, newest first."""
    gym_day_ids = [day.id for day in routine.gym_days]
    return (
        db.query(LoggedSession)
        .options(joinedload(LoggedSession.results))
        .filter(LoggedSession.gym_day_id.in_(gym_day_ids))
        .order_by(LoggedSession.logged_at.desc())
        .all()
    )
