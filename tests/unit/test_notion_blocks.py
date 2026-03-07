import pytest
from datetime import date
from life_os.integrations.notion_store import _build_sitting, _build_habits
from life_os.models.wellness import SittingEntry, HabitEntry, HabitCategory

@pytest.mark.asyncio
async def test_build_sitting():
    s = SittingEntry(date=date(2026, 3, 1), duration_minutes=60, took_from="Daaji")
    blocks = await _build_sitting([s])
    assert len(blocks) == 1
    content = blocks[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"]
    assert "Daaji" in content
    assert "60 mins" in content
    assert "🪷" in content

@pytest.mark.asyncio
async def test_build_habits():
    h = HabitEntry(date=date(2026, 3, 1), category=HabitCategory.JUNK_FOOD, description="Chips")
    blocks = await _build_habits([h])
    assert len(blocks) == 1
    content = blocks[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"]
    assert "🍔" in content
    assert "Junk Food" in content
    assert "Chips" in content
