"""Persistence Node

Saves any extracted entity data to long-term storage (SQLite/Notion).
Builds a clean, per-section confirmation message reflecting everything logged.
"""

from typing import Any

import structlog

from life_os.agent.state import AgentState
from life_os.integrations.bigquery_store import save_records
from life_os.integrations.notion_store import append_notion_blocks

log = structlog.get_logger(__name__)

_ICONS: dict[str, str] = {
    "sleep": "🛏️ Sleep",
    "exercise": "🏃 Exercise",
    "meditation": "🧘 Meditation",
    "cleaning": "🧹 Cleaning",
    "sitting": "🪷 Sitting",
    "group_meditation": "🕊️ Group Meditation",
    "habits": "📊 Habit Tracker",
    "tasks": "✅ Tasks",
    "reading_links": "🔖 Reading",
    "journal_note": "📝 Journal",
}


def _summarise_sleep(obj: Any) -> str:
    parts = []
    if obj.get("date"):
        parts.append(f"Date: {obj.get('date')}")
    if obj.get("duration_hours"):
        parts.append(f"{obj.get('duration_hours')} hrs")
    if obj.get("bedtime_hour") is not None:
        minute = obj.get("bedtime_minute") or 0
        parts.append(f"Bed: {obj.get('bedtime_hour'):02d}:{minute:02d}")
    if obj.get("wake_hour") is not None:
        minute = obj.get("wake_minute") or 0
        parts.append(f"Woke: {obj.get('wake_hour'):02d}:{minute:02d}")
    if obj.get("quality"):
        parts.append(f"Quality: {obj.get('quality')}")
    return ", ".join(parts)


def _summarise_exercise(items: list[Any]) -> str:
    summaries = []
    for ex in items:
        parts = []
        if ex.get("exercise_type"):
            parts.append(str(ex.get("exercise_type")).title())
        if ex.get("duration_minutes"):
            parts.append(f"{ex.get('duration_minutes')} mins")
        if ex.get("distance_km"):
            parts.append(f"{ex.get('distance_km')} km")
        if ex.get("intensity"):
            parts.append(f"Intensity: {ex.get('intensity')}/10")
        if ex.get("body_parts"):
            bparts = [str(bp).replace('_', ' ').title() for bp in ex.get("body_parts")]
            parts.append(f"Body: {', '.join(bparts)}")
        summaries.append(", ".join(parts) if parts else "Session logged")
    return " | ".join(summaries)


def _summarise_practice(name: str, items: list[Any]) -> str:
    from datetime import datetime
    summaries = []
    for p in items:
        parts = []
        if p.get("datetime_logged"):
            try:
                dt = datetime.fromisoformat(p["datetime_logged"])
                parts.append(f"@{dt.strftime('%H:%M')}")
            except Exception:
                pass
        if p.get("duration_minutes"):
            parts.append(f"{p['duration_minutes']} mins")
        if p.get("took_from"):
            parts.append(f"From: {p['took_from']}")
        if p.get("place"):
            parts.append(f"At: {p['place']}")
        summaries.append(" | ".join(parts) if parts else "Logged")
    return ", ".join(summaries)


def _summarise_habits(items: list[Any]) -> str:
    from datetime import datetime
    summaries = []
    for h in items:
        dt_str = ""
        if h.get("datetime_logged"):
            try:
                dt = datetime.fromisoformat(h["datetime_logged"])
                dt_str = f"@{dt.strftime('%H:%M')} "
            except Exception:
                pass
        cat = str(h.get("category", "other")).replace("_", " ").title()
        desc = h.get("description", "")
        summaries.append(f"{dt_str}{cat}: {desc}")
    return " | ".join(summaries)


async def run(state: AgentState) -> dict[str, Any]:
    """Save extracted entities to the database and build a clean summary.

    Args:
        state: Current agent state containing extracted entities.

    Returns:
        Updated state with response_message and cleared entities.
    """
    user_id = state["user_id"]
    entities = state.get("entities", {})

    if not entities:
        log.warning("no_records_to_write", user_id=user_id)
        return {"response_message": "No data extracted to save."}

    records_to_save = []
    logged_sections: list[str] = []

    # ── Auto-fill missing datetime_logged ──────────────────────────
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from life_os.config.settings import settings
    
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    for practice_key in ['meditation', 'cleaning', 'sitting', 'group_meditation', 'habits']:
        items = entities.get(practice_key, [])
        for item in items:
            if isinstance(item, dict) and item.get('datetime_logged') is None:
                item['datetime_logged'] = now.isoformat()

    # ── Process each entity type ──────────────────────────────────────────
    sleep = entities.get("sleep")
    exercise = entities.get("exercise") or []
    journal_note = entities.get("journal_note")
    notion_tasks = entities.get("tasks") or []
    notion_links = entities.get("reading_links") or []

    is_test = state.get("is_test", False)

    if sleep and isinstance(sleep, dict):
        records_to_save.append({**sleep, "type": "sleep", "is_test": is_test})
        logged_sections.append(f"{_ICONS['sleep']}: {_summarise_sleep(sleep)}")

    if exercise:
        for ex in exercise:
            if isinstance(ex, dict):
                records_to_save.append({**ex, "type": "exercise", "is_test": is_test})
        logged_sections.append(f"{_ICONS['exercise']}: {_summarise_exercise(exercise)}")

    for p_key in ['meditation', 'cleaning', 'sitting', 'group_meditation']:
        p_items = entities.get(p_key) or []
        for p in p_items:
            if isinstance(p, dict):
                records_to_save.append({**p, "type": p_key, "is_test": is_test})
        if p_items:
            logged_sections.append(f"{_ICONS[p_key]}: {_summarise_practice(p_key, p_items)}")

    habits = entities.get("habits") or []
    for h in habits:
        if isinstance(h, dict):
            records_to_save.append({**h, "type": "habit", "is_test": is_test})
    if habits:
        logged_sections.append(f"{_ICONS['habits']}: {_summarise_habits(habits)}")

    if journal_note:
        records_to_save.append({"type": "journal_note", "note": journal_note, "is_test": is_test})
        preview = journal_note if len(journal_note) <= 80 else journal_note[:77] + "..."
        logged_sections.append(f"{_ICONS['journal_note']}: {preview}")

    if notion_tasks:
        for task in notion_tasks:
            if isinstance(task, dict):
                records_to_save.append({**task, "type": "tasks", "is_test": is_test})
        task_names = ", ".join(t.get("task", "") for t in notion_tasks if isinstance(t, dict))
        logged_sections.append(f"{_ICONS['tasks']}: {task_names}")

    if notion_links:
        for link in notion_links:
            if isinstance(link, dict):
                records_to_save.append({**link, "type": "reading_links", "is_test": is_test})
        logged_sections.append(f"{_ICONS['reading_links']}: {len(notion_links)} link(s) saved")

    # ── Build the response ────────────────────────────────────────────────
    if not logged_sections:
        return {"response_message": "I could not find any data to save in your message."}

    response_parts = ["I have logged the following:\n" + "\n".join(logged_sections)]

    # ── Notion sync — reconstruct Pydantic models from plain dicts ────────
    if len(records_to_save) > 0 and not is_test:
        from life_os.models.tasks import ReadingLink, TaskItem
        from life_os.models.wellness import (
            CleaningEntry,
            ExerciseEntry,
            GroupMeditationEntry,
            HabitEntry,
            MeditationEntry,
            SittingEntry,
            SleepEntry,
        )

        n_sleep = SleepEntry(**sleep) if sleep and isinstance(sleep, dict) else None
        n_ex = [ExerciseEntry(**x) for x in exercise if isinstance(x, dict)] or None
        n_med = [MeditationEntry(**i) for i in entities.get("meditation", []) if isinstance(i, dict)] or None
        n_clean = [CleaningEntry(**i) for i in entities.get("cleaning", []) if isinstance(i, dict)] or None
        n_sit = [SittingEntry(**i) for i in entities.get("sitting", []) if isinstance(i, dict)] or None
        n_group = [GroupMeditationEntry(**i) for i in entities.get("group_meditation", []) if isinstance(i, dict)] or None
        n_habits = [HabitEntry(**i) for i in entities.get("habits", []) if isinstance(i, dict)] or None
        
        n_tasks = [TaskItem(**t) for t in notion_tasks if isinstance(t, dict)] or None
        n_links = [ReadingLink(**lnk) for lnk in notion_links if isinstance(lnk, dict)] or None

        notion_journal_note = journal_note

        failed_syncs = await append_notion_blocks(
            tasks=n_tasks,
            links=n_links,
            sleep=n_sleep,
            exercise=n_ex,
            meditation=n_med,
            cleaning=n_clean,
            sitting=n_sit,
            group_meditation=n_group,
            habits=n_habits,
            journal_note=notion_journal_note,
        )
        if not failed_syncs:
            response_parts.append("✨ Synced to Notion!")
        else:
            response_parts.append(f"⚠️ Partial Notion sync — failed: {', '.join(failed_syncs)}")

    # ── SQLite save ───────────────────────────────────────────────────────
    if records_to_save:
        await save_records(user_id=user_id, records=records_to_save)
        log.info("saved_records", count=len(records_to_save), user_id=user_id)

    final_response = "\n".join(response_parts)

    # Wipe entities so they don't bleed into next turn
    return {
        "structured_records": records_to_save,
        "response_message": final_response,
        "entities": {},
        "missing_fields": [],
        "clarification_count": 0,
    }
