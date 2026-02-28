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


class SleepQuality(enum.StrEnum):
    # Subjective sleep quality rating.
    POOR = "poor"
    FAIR = "fair"
    GOOD = "good"
    EXCELLENT = "excellent"


class SleepEntry(BaseModel):
    """A single night of sleep data.

    Attributes:
        date: Calendar date of the sleep entry.
        bedtime_hour: Hour of night (0-23) when user went to sleep.
        bedtime_minute: Minute when user went to sleep.
        wake_hour: Hour of morning (0-23) when user woke up.
        wake_minute: Minute when user woke up.
        duration_hours: Computed sleep duration in decimal hours.
        quality: Subjective quality rating.
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
    quality: SleepQuality | None = None
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
        return self

    @field_validator("bedtime_hour")
    @classmethod
    def validate_bedtime_is_evening(cls, v: int | None) -> int | None:
        """Warn if bedtime looks like daytime (potential extraction error)."""
        if v is not None and 9 <= v <= 17:
            raise ValueError(f"Bedtime hour {v} looks like daytime — check extraction")
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
    intensity: Annotated[int, Field(ge=1, le=10)] | None = Field(default=None)
    notes: str | None = Field(default=None, max_length=500)


class MeditationType(enum.StrEnum):
    MEDITATION = "meditation"  # General / unspecified sitting meditation
    CLEANING = "cleaning"  # Heartfulness cleaning practice
    SITTING = "sitting"  # Heartfulness sitting / transmission practice
    GROUP_MEDITATION = "group_meditation"  # Satsang / group sitting
    OTHER = "other"


class WellnessEntry(BaseModel):
    # Daily wellness log: meditation, mood, energy.

    date: dt_date
    time_of_day: str | None = Field(
        default=None,
        description="Time of the session, e.g. '07:30' or '7am', if the user specifies it",
    )
    meditation_minutes: Annotated[int, Field(ge=0)] | None = None
    meditation_type: MeditationType | None = Field(
        default=None,
        description=(
            "Type of practice: 'meditation' (general), 'cleaning', 'sitting', "
            "'group_meditation' (satsang/group sitting), or 'other'"
        ),
    )
    mood_score: Annotated[int, Field(ge=1, le=10)] | None = None
    energy_level: Annotated[int, Field(ge=1, le=10)] | None = None
    notes: str | None = Field(default=None, max_length=1000)


class ExtractedData(BaseModel):
    """Container for all data extracted from a single user message.

    Fields are all optional because a message might contain only
    sleep data, only exercise, or any combination."""

    sleep: SleepEntry | None = None
    exercise: list[ExerciseEntry] = Field(default_factory=list)
    wellness: WellnessEntry | None = None
    tasks: list[TaskItem] = Field(default_factory=list)
    reading_links: list[ReadingLink] = Field(default_factory=list)
    reminder_text: str | None = None
    reminder_datetime: dt_datetime | None = None
    journal_note: str | None = None
