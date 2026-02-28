"""Unit tests for the entity extraction node.

Uses pytest-asyncio and a mock Instructor client to avoid real API calls.
Tests extraction accuracy on golden examples.
"""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from life_os.agent.nodes.extractor import run
from life_os.models.wellness import ExtractedData, SleepEntry, SleepQuality


@pytest.mark.asyncio
async def test_extracts_sleep_data(base_state: dict) -> None:
    """Extractor should populate SleepEntry from a natural message."""
    base_state["raw_input"] = "slept at 11pm, woke up at 630, slept really well"

    mock_result = ExtractedData(
        sleep=SleepEntry(
            date=date.today(),
            bedtime_hour=23,
            bedtime_minute=0,
            wake_hour=6,
            wake_minute=30,
            quality=SleepQuality.EXCELLENT,
        )
    )

    with patch("life_os.agent.nodes.extractor._call_llm", AsyncMock(return_value=mock_result)):
        result = await run(base_state)

    assert result["entities"]["sleep"] is not None
    assert result["entities"]["sleep"].duration_hours == 7.5
    assert result["entities"]["sleep"].quality == SleepQuality.EXCELLENT


@pytest.mark.asyncio
async def test_merges_with_existing_entities(base_state: dict) -> None:
    """Extractor must not overwrite confirmed entities from prior turns."""
    # Pre-confirmed sleep from turn 1
    confirmed_sleep = SleepEntry(
        date=date.today(), bedtime_hour=22, bedtime_minute=0, wake_hour=7, wake_minute=0
    )
    base_state["entities"] = {"sleep": confirmed_sleep}
    base_state["raw_input"] = "I also meditated for 20 minutes"

    mock_result = ExtractedData()  # No sleep in new message

    with patch("life_os.agent.nodes.extractor._call_llm", AsyncMock(return_value=mock_result)):
        result = await run(base_state)

    # Sleep from turn 1 must be preserved
    assert result["entities"]["sleep"].bedtime_hour == 22
