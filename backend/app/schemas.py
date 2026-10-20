from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCredentials(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


class ExerciseDefinitionIn(BaseModel):
    muscle_group: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    sets: int = Field(ge=1, le=20)
    rep_range_low: int = Field(ge=1, le=100)
    rep_range_high: int = Field(ge=1, le=100)


class ExerciseDefinitionOut(ExerciseDefinitionIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class GymDayIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    exercises: list[ExerciseDefinitionIn] = Field(min_length=1)


class GymDayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    exercises: list[ExerciseDefinitionOut]


class RoutineIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    gym_days: list[GymDayIn] = Field(min_length=1)


class RoutineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool
    gym_days: list[GymDayOut]


class RoutineSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool


class ExerciseResultIn(BaseModel):
    exercise_definition_id: int
    weight_lb: float = Field(ge=0, le=2000)
    reps_done: int = Field(ge=0, le=200)


class LogSessionIn(BaseModel):
    gym_day_id: int
    results: list[ExerciseResultIn] = Field(min_length=1)


class ExerciseResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exercise_definition_id: int
    weight_lb: float
    reps_done: int


class LoggedSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gym_day_id: int
    logged_at: datetime
    results: list[ExerciseResultOut]


class ExerciseProgressPoint(BaseModel):
    logged_at: datetime
    weight_lb: float
    reps_done: int


class AssistantGymDayOut(BaseModel):
    id: int
    name: str


class AssistantExerciseOut(BaseModel):
    id: int
    name: str
    muscle_group: str
    gym_day: str
    latest: ExerciseProgressPoint | None
    best_30d: ExerciseProgressPoint | None


class AssistantSummaryOut(BaseModel):
    username: str
    routine: RoutineSummary | None
    next_gym_day: AssistantGymDayOut | None
    last_session_date: date | None
    exercises: list[AssistantExerciseOut]
