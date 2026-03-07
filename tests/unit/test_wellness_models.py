import pytest
from datetime import date, datetime

from life_os.models.wellness import (
    MeditationEntry,
    CleaningEntry,
    SittingEntry,
    GroupMeditationEntry,
    HabitEntry,
    HabitCategory,
)

def test_meditation_model():
    m = MeditationEntry(date=date(2026, 3, 1), duration_minutes=30)
    assert m.duration_minutes == 30
    assert m.datetime_logged is None

def test_cleaning_model():
    c = CleaningEntry(date=date(2026, 3, 1), duration_minutes=45)
    assert c.duration_minutes == 45
    assert c.notes is None

def test_sitting_model():
    s = SittingEntry(date=date(2026, 3, 1), duration_minutes=60, took_from="Daaji")
    assert s.duration_minutes == 60
    assert s.took_from == "Daaji"

def test_group_meditation_model():
    gm = GroupMeditationEntry(date=date(2026, 3, 1), duration_minutes=45, place="Ashram")
    assert gm.duration_minutes == 45
    assert gm.place == "Ashram"

def test_habit_model():
    h = HabitEntry(
        date=date(2026, 3, 1), 
        category=HabitCategory.JUNK_FOOD, 
        description="Ate a tub of ice cream"
    )
    assert h.category == HabitCategory.JUNK_FOOD
    assert h.description == "Ate a tub of ice cream"
