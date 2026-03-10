"""Pydantic v2 data models for all wellness tracking categories.

These models are used throughout the agent for:
- LLM output validation via Instructor
- SQLite persistence via aiosqlite
- Notion/Calendar integration payloads
"""

from __future__ import annotations

import enum
from datetime import date as dt_date
from datetime import datetime as dt_datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from life_os.models.tasks import ReadingLink, TaskItem


class SleepEntry(BaseModel):
    """A single night of sleep data.

    Attributes:
        date: Calendar date of the sleep entry.
        bedtime_hour: Hour of night (0-23) when user went to sleep.
        bedtime_minute: Minute when user went to sleep.
        wake_hour: Hour of morning (0-23) when user woke up.
        wake_minute: Minute when user woke up.
        duration_hours: Computed sleep duration in decimal hours.
        quality: Subjective quality rating from 1 to 10. Automatically computes to 10 if excellent.
        notes: Optional free-text notes.
    """

    date: dt_date = Field(description="Calendar date of the sleep")
    bedtime_hour: Annotated[int, Field(ge=0, le=23)] | None = Field(
        default=None, description="Hour went to sleep"
    )
    bedtime_minute: Annotated[int, Field(ge=0, le=59)] | None = Field(default=None)
    wake_hour: Annotated[int, Field(ge=0, le=23)] | None = Field(
        default=None, description="Hour woke up"
    )
    wake_minute: Annotated[int, Field(ge=0, le=59)] | None = Field(default=None)
    duration_hours: float | None = Field(
        default=None, description="Total sleep duration if specific times are not given"
    )
    quality: Annotated[int, Field(ge=1, le=10)] | None = Field(default=None, description="Quality rating from 1-10")
    notes: str | None = None

    @model_validator(mode="after")
    def compute_duration(self) -> SleepEntry:
        # Calculate duration if exact times are given
        if self.bedtime_hour is not None and self.wake_hour is not None:
            bed_m = self.bedtime_minute or 0
            wake_m = self.wake_minute or 0

            bed_total_mins = self.bedtime_hour * 60 + bed_m
            wake_total_mins = self.wake_hour * 60 + wake_m

            if wake_total_mins <= bed_total_mins:
                wake_total_mins += 24 * 60

            calculated_duration = (wake_total_mins - bed_total_mins) / 60.0

            # Use calculated duration if none is explicitly provided, or override
            if self.duration_hours is None:
                self.duration_hours = round(calculated_duration, 2)

        # Auto-calculate excellent quality rating
        if self.duration_hours is not None and self.bedtime_hour is not None:
            if self.bedtime_hour <= 22 and self.duration_hours >= 7.5:
                if self.quality is None:
                    self.quality = 10

        return self

    @field_validator("bedtime_hour")
    @classmethod
    def validate_bedtime_is_evening(cls, v: int | None) -> int | None:
        """Warn if bedtime looks like daytime (potential extraction error)."""
        if v is not None and 9 <= v <= 17:
            import structlog
            structlog.get_logger(__name__).warning("unusual_bedtime", hour=v)
        return v


class ExerciseType(enum.StrEnum):
    RUN = "run"
    WALK = "walk"
    GYM = "gym"
    WEIGHTS = "weights"  # alias for gym-specific weight training
    YOGA = "yoga"
    SWIM = "swim"
    CYCLE = "cycle"
    OTHER = "other"


class MuscleGroup(enum.StrEnum):
    FULL_BODY = "full_body"
    CHEST = "chest"
    BICEPS = "biceps"
    TRICEPS = "triceps"
    SHOULDERS = "shoulders"
    BACK = "back"
    ABS = "abs"
    LOWER_BODY = "lower_body"  # legs, glutes, hamstrings, quads
    OTHER = "other"


class ExerciseEntry(BaseModel):
    """A single exercise / training session."""

    date: dt_date
    exercise_type: ExerciseType | None = None
    body_parts: list[MuscleGroup] | None = Field(
        default=None,
        description=(
            "Muscle groups trained — only for gym/weights sessions. "
            "Options: full_body, chest, biceps, triceps, shoulders, back, abs, lower_body."
        ),
    )
    duration_minutes: Annotated[int, Field(gt=0, le=600)] | None = None
    distance_km: Annotated[float, Field(ge=0)] | None = None
    intensity: Annotated[int, Field(ge=1, le=10)] | None = Field(
        default=None, 
        description="Intensity score from 1-10. If the user uses words like 'intense', 'hard', 'tiring', infer a score of 8 or 9."
    )
    notes: str | None = Field(default=None, max_length=500)


class PracticeBase(BaseModel):
    """Base for all spiritual practices."""
    date: dt_date
    datetime_logged: dt_datetime | None = Field(
        default=None,
        description=(
            "The datetime when the practice was done. "
            "If user specifies a time, combine with date. "
            "If not specified, leave null and system will auto-fill."
        ),
    )
    duration_minutes: Annotated[int, Field(ge=1, le=300)] | None = None
    notes: str | None = Field(default=None, max_length=1000)


class MeditationEntry(PracticeBase):
    """General / unspecified meditation session."""
    pass


class CleaningEntry(PracticeBase):
    """Heartfulness cleaning practice session."""
    pass


class SittingEntry(PracticeBase):
    """Heartfulness sitting / transmission practice."""
    took_from: str | None = Field(
        default=None,
        description="Name of the trainer/preceptor who gave the sitting"
    )


class GroupMeditationEntry(PracticeBase):
    """Satsang / group meditation session."""
    place: str | None = Field(
        default=None,
        description="Location/venue of the group meditation"
    )


class HabitCategory(enum.StrEnum):
    SELF_CONTROL = "lost_self_control"
    JUNK_FOOD = "junk_food"
    OUTSIDE_FOOD = "outside_food"
    LATE_EATING = "late_eating"
    SCREEN_TIME = "screen_time"
    OTHER = "other"


class HabitEntry(BaseModel):
    """A habit event to track (typically negative habits to be mindful of)."""
    date: dt_date
    datetime_logged: dt_datetime | None = None
    category: HabitCategory
    description: str = Field(
        description='What happened, e.g. ate ice cream, ordered Deliveroo, watched Netflix till 2am'
    )
    notes: str | None = None


class ExtractedData(BaseModel):
    """Container for all data extracted from a single user message.

    Fields are all optional because a message might contain only
    sleep data, only exercise, or any combination."""

    sleep: SleepEntry | None = None
    exercise: list[ExerciseEntry] = Field(default_factory=list)
    meditation: list[MeditationEntry] = Field(default_factory=list)
    cleaning: list[CleaningEntry] = Field(default_factory=list)
    sitting: list[SittingEntry] = Field(default_factory=list)
    group_meditation: list[GroupMeditationEntry] = Field(default_factory=list)
    habits: list[HabitEntry] = Field(default_factory=list)
    tasks: list[TaskItem] = Field(default_factory=list)
    reading_links: list[ReadingLink] = Field(default_factory=list)
    journal_note: str | None = None
