"""Notion API integration for appending tasks and reading links."""

from datetime import date
from typing import Any

import structlog
from notion_client import AsyncClient
from tenacity import retry, stop_after_attempt, wait_exponential

from life_os.config.settings import settings
from life_os.models.tasks import ReadingLink, TaskItem
from life_os.models.wellness import ExerciseEntry, SleepEntry, WellnessEntry

log = structlog.get_logger(__name__)

_notion_client: AsyncClient | None = None


def _get_notion() -> AsyncClient:
    global _notion_client
    if _notion_client is None:
        if not settings.notion_api_key:
            raise RuntimeError("NOTION_API_KEY not set")
        _notion_client = AsyncClient(auth=settings.notion_api_key.get_secret_value())
    return _notion_client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=8), reraise=True)
async def _append_blocks(
    notion: AsyncClient, block_id: str, children: list[dict[str, Any]]
) -> None:
    await notion.blocks.children.append(block_id=block_id, children=children)


async def append_notion_blocks(
    tasks: list[TaskItem] | None = None,
    links: list[ReadingLink] | None = None,
    sleep: SleepEntry | None = None,
    exercise: list[ExerciseEntry] | None = None,
    wellness: WellnessEntry | None = None,
    journal_note: str | None = None,
) -> list[str]:
    """Append extracted tasks, links, and wellness data to Notion pages.
    Returns a list of keys that failed to sync."""
    if not settings.enable_notion or not settings.notion_api_key:
        log.info("notion_disabled_or_missing_key")
        return []

    notion = _get_notion()
    failed = []

    # --- Append Tasks ---
    if tasks and settings.notion_to_do_page_id:
        task_blocks = []
        for t in tasks:
            priority_str = ""
            if t.priority == 1:
                priority_str = " 🔥 [High]"
            elif t.priority == 2:
                priority_str = " ⚡ [Med]"
            elif t.priority == 3:
                priority_str = " 💡 [Low]"

            task_blocks.append(
                {
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": [
                            {"type": "text", "text": {"content": f"{t.task}{priority_str}"}}
                        ],
                        "checked": False,
                    },
                }
            )
        try:
            await _append_blocks(notion, settings.notion_to_do_page_id, task_blocks)
            log.info("notion_tasks_appended", count=len(tasks))
        except Exception as exc:
            log.error("notion_tasks_failed", error=str(exc))
            failed.append("tasks")

    # --- Append Links ---
    if links and settings.notion_to_read_page_id:
        link_blocks = []
        for link in links:
            content = "🔖 "
            if link.context:
                content += f"{link.context} - "
            url = link.url_str()
            content += url

            link_blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": content, "link": {"url": url}},
                            }
                        ]
                    },
                }
            )
        try:
            await _append_blocks(notion, settings.notion_to_read_page_id, link_blocks)
            log.info("notion_links_appended", count=len(links))
        except Exception as exc:
            log.error("notion_links_failed", error=str(exc))
            failed.append("reading_links")

    # --- Append Sleep ---
    if sleep and settings.notion_sleep_page_id:
        text = f"🛏️ Date: {sleep.date} | Duration: {sleep.duration_hours} hrs"
        if sleep.quality:
            text += f" | Quality: {sleep.quality}"
        if sleep.notes:
            text += f" | Notes: {sleep.notes}"

        try:
            await _append_blocks(
                notion,
                settings.notion_sleep_page_id,
                [
                    {
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [{"type": "text", "text": {"content": text}}]
                        },
                    }
                ],
            )
            log.info("notion_sleep_appended")
        except Exception as exc:
            log.error("notion_sleep_failed", error=str(exc))
            failed.append("sleep")

    # --- Append Exercise ---
    if exercise and settings.notion_exercise_page_id:
        ex_blocks = []
        for ex in exercise:
            text = (
                f"🏃 Date: {ex.date} | {ex.exercise_type.title()} | "
                f"{ex.duration_minutes} mins | Intensity: {ex.intensity}"
            )
            if ex.distance_km:
                text += f" | Distance: {ex.distance_km}km"
            if getattr(ex, "body_parts", None):
                bparts_str = [str(getattr(bp, "value", bp)).replace('_', ' ').title() for bp in ex.body_parts]
                text += f" | Body: {', '.join(bparts_str)}"
            if ex.notes:
                text += f" | Notes: {ex.notes}"

            ex_blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": text}}]
                    },
                }
            )

        try:
            await _append_blocks(notion, settings.notion_exercise_page_id, ex_blocks)
            log.info("notion_exercise_appended")
        except Exception as exc:
            log.error("notion_exercise_failed", error=str(exc))
            failed.append("exercise")

    # --- Append Wellness ---
    if wellness and settings.notion_wellness_page_id:
        text = f"🧘 Date: {wellness.date}"
        if getattr(wellness, "time_of_day", None):
            text += f" @ {wellness.time_of_day}"
        if wellness.meditation_minutes:
            text += f" | Meditation: {wellness.meditation_minutes} mins"
        if wellness.meditation_type:
            text += f" ({wellness.meditation_type.replace('_', ' ').title()})"
        if wellness.mood_score:
            text += f" | Mood: {wellness.mood_score}/10"
        if wellness.energy_level:
            text += f" | Energy: {wellness.energy_level}/10"
        if wellness.notes:
            text += f" | Notes: {wellness.notes}"

        try:
            await _append_blocks(
                notion,
                settings.notion_wellness_page_id,
                [
                    {
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [{"type": "text", "text": {"content": text}}]
                        },
                    }
                ],
            )
            log.info("notion_wellness_appended")
        except Exception as exc:
            log.error("notion_wellness_failed", error=str(exc))
            failed.append("wellness")

    # --- Append Journal ---
    if journal_note and settings.notion_journal_page_id:
        text = f"📝 {date.today()}: {journal_note}"
        try:
            await _append_blocks(
                notion,
                settings.notion_journal_page_id,
                [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
                    }
                ],
            )
            log.info("notion_journal_appended")
        except Exception as exc:
            log.error("notion_journal_failed", error=str(exc))
            failed.append("journal_note")

    return failed
