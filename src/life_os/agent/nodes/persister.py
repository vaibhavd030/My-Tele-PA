"""Persistence Node

Saves any extracted entity data to long-term storage (SQLite/Notion).
Builds a clean, per-section confirmation message reflecting everything logged.
"""

from typing import Any

import structlog

from life_os.agent.state import AgentState
from life_os.integrations.notion_store import append_notion_blocks
from life_os.integrations.sqlite_store import save_records

log = structlog.get_logger(__name__)

# Emoji icons per entity type for a friendly confirmation message
_ICONS: dict[str, str] = {
    "sleep": "🛏️ Sleep",
    "exercise": "🏃 Exercise",
    "wellness": "🧘 Wellness",
    "tasks": "✅ Tasks",
    "reading_links": "🔖 Reading",
    "journal_note": "📝 Journal",
}


def _summarise_sleep(obj: Any) -> str:
    parts = []
    if getattr(obj, "date", None):
        parts.append(f"Date: {obj.date}")
    if getattr(obj, "duration_hours", None):
        parts.append(f"{obj.duration_hours} hrs")
    if getattr(obj, "bedtime_hour", None) is not None:
        minute = getattr(obj, "bedtime_minute", 0) or 0
        parts.append(f"Bed: {obj.bedtime_hour:02d}:{minute:02d}")
    if getattr(obj, "wake_hour", None) is not None:
        minute = getattr(obj, "wake_minute", 0) or 0
        parts.append(f"Woke: {obj.wake_hour:02d}:{minute:02d}")
    if getattr(obj, "quality", None):
        parts.append(f"Quality: {obj.quality}")
    return ", ".join(parts)


def _summarise_exercise(items: list[Any]) -> str:
    summaries = []
    for ex in items:
        parts = []
        if getattr(ex, "exercise_type", None):
            parts.append(str(ex.exercise_type).title())
        if getattr(ex, "duration_minutes", None):
            parts.append(f"{ex.duration_minutes} mins")
        if getattr(ex, "distance_km", None):
            parts.append(f"{ex.distance_km} km")
        if getattr(ex, "intensity", None):
            parts.append(f"Intensity: {ex.intensity}/10")
        summaries.append(", ".join(parts) if parts else "Session logged")
    return " | ".join(summaries)


def _summarise_wellness(obj: Any) -> str:
    parts = []
    if getattr(obj, "time_of_day", None):
        parts.append(f"@ {obj.time_of_day}")
    if getattr(obj, "meditation_minutes", None):
        med_str = f"{obj.meditation_minutes} mins"
        if getattr(obj, "meditation_type", None):
            med_str += f" ({str(obj.meditation_type).replace('_', ' ').title()})"
        parts.append(med_str)
    if getattr(obj, "mood_score", None):
        parts.append(f"Mood: {obj.mood_score}/10")
    if getattr(obj, "energy_level", None):
        parts.append(f"Energy: {obj.energy_level}/10")
    return ", ".join(parts)


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

    # ── Process each entity type ──────────────────────────────────────────
    sleep = entities.get("sleep")
    exercise = entities.get("exercise") or []
    wellness = entities.get("wellness")
    journal_note = entities.get("journal_note")
    notion_tasks = entities.get("tasks") or []
    notion_links = entities.get("reading_links") or []

    if sleep:
        records_to_save.append({**sleep.model_dump(exclude_none=True), "type": "sleep"})
        logged_sections.append(f"{_ICONS['sleep']}: {_summarise_sleep(sleep)}")

    if exercise:
        for ex in exercise:
            records_to_save.append({**ex.model_dump(exclude_none=True), "type": "exercise"})
        logged_sections.append(f"{_ICONS['exercise']}: {_summarise_exercise(exercise)}")

    if wellness:
        records_to_save.append({**wellness.model_dump(exclude_none=True), "type": "wellness"})
        summary = _summarise_wellness(wellness)
        section = f"{_ICONS['wellness']}: {summary}" if summary else _ICONS["wellness"]
        logged_sections.append(section)

    if journal_note:
        records_to_save.append({"type": "journal_note", "note": journal_note})
        # Truncate for the confirmation message
        preview = journal_note if len(journal_note) <= 80 else journal_note[:77] + "..."
        logged_sections.append(f"{_ICONS['journal_note']}: {preview}")

    if notion_tasks:
        for task in notion_tasks:
            records_to_save.append({**task.model_dump(exclude_none=True), "type": "tasks"})
        task_names = ", ".join(t.task for t in notion_tasks)
        logged_sections.append(f"{_ICONS['tasks']}: {task_names}")

    if notion_links:
        for link in notion_links:
            records_to_save.append({**link.model_dump(exclude_none=True), "type": "reading_links"})
        logged_sections.append(f"{_ICONS['reading_links']}: {len(notion_links)} link(s) saved")

    # ── Build the response ────────────────────────────────────────────────
    if not logged_sections:
        return {"response_message": "I could not find any data to save in your message."}

    response_parts = ["I have logged the following:\n" + "\n".join(logged_sections)]

    # ── Notion sync ───────────────────────────────────────────────────────
    if sleep or exercise or wellness or journal_note or notion_tasks or notion_links:
        failed_syncs = await append_notion_blocks(
            tasks=notion_tasks or None,
            links=notion_links or None,
            sleep=sleep,
            exercise=exercise or None,
            wellness=wellness,
            journal_note=journal_note,
        )
        if not failed_syncs:
            response_parts.append("✨ Synced to Notion!")
        else:
            response_parts.append(f"⚠️ Partial Notion sync — failed: {', '.join(failed_syncs)}")

    # ── SQLite save ───────────────────────────────────────────────────────
    if records_to_save:
        await save_records(user_id=user_id, records=records_to_save)
        log.info("saved_records_to_sqlite", count=len(records_to_save), user_id=user_id)

    final_response = "\n".join(response_parts)

    # Wipe entities so they don't bleed into next turn
    return {
        "structured_records": records_to_save,
        "response_message": final_response,
        "entities": {},
        "missing_fields": [],
        "clarification_count": 0,
    }
