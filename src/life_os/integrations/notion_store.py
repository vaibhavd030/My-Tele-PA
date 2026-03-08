"""Notion API integration for appending tasks and reading links."""

import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx
import structlog
from notion_client import AsyncClient
from tenacity import retry, stop_after_attempt, wait_exponential

from life_os.config.settings import settings
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

log = structlog.get_logger(__name__)

_notion_client: AsyncClient | None = None

def _get_now_formatted() -> str:
    now = datetime.now()
    time_str = now.strftime("%I:%M%p").lstrip("0").lower()
    return f"{now.day} {now.strftime('%B %Y')} {time_str}"

def _format_date_only(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"

def _bullet_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _get_notion() -> AsyncClient:
    global _notion_client
    if _notion_client is None:
        if not settings.notion_api_key:
            raise RuntimeError("NOTION_API_KEY not set")
        _notion_client = AsyncClient(auth=settings.notion_api_key.get_secret_value())
    return _notion_client


async def fetch_title(url: str) -> str:
    """Asynchronously fetch the title of a web page."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, follow_redirects=True)
            match = re.search(r"<title>(.*?)</title>", resp.text, flags=re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()
    except Exception as e:
        log.debug("fetch_title_failed", url=url, error=str(e))
    return ""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=8), reraise=True)
async def _append_blocks(
    notion: AsyncClient, block_id: str, children: list[dict[str, Any]]
) -> None:
    await notion.blocks.children.append(block_id=block_id, children=children)





@dataclass
class SyncConfig:
    page_id_attr: str
    block_builder: Callable[[Any], Coroutine[Any, Any, list[dict[str, Any]]]]


async def _build_tasks(tasks: list[TaskItem]) -> list[dict[str, Any]]:
    task_blocks = []
    for t in tasks:
        priority_str = ""
        if t.priority == 1:
            priority_str = " 🔥 [High]"
        elif t.priority == 2:
            priority_str = " ⚡ [Med]"
        elif t.priority == 3:
            priority_str = " 💡 [Low]"
        task_blocks.append({
            "object": "block",
            "type": "to_do",
            "to_do": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": f"[{_get_now_formatted()}] {t.task}{priority_str}"}
                    }
                ],
                "checked": False,
            },
        })
    return task_blocks

async def _build_links(links: list[ReadingLink]) -> list[dict[str, Any]]:
    link_blocks = []
    for link in links:
        url = link.url_str()
        title = await fetch_title(url)
        prefix_content = f"🔖 {_get_now_formatted()}: "
        if link.context:
            prefix_content += f"{link.context} - "
        link_text = title if title else url
        link_blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": prefix_content}},
                    {"type": "text", "text": {"content": link_text, "link": {"url": url}}},
                ]
            },
        })
    return link_blocks

async def _build_sleep(sleep: SleepEntry) -> list[dict[str, Any]]:
    text = f"🛏️ Date: {_format_date_only(sleep.date)} | Duration: {sleep.duration_hours} hrs"
    times = []
    if sleep.bedtime_hour is not None:
        bm = f"{sleep.bedtime_minute:02d}" if sleep.bedtime_minute else "00"
        times.append(f"Bed: {sleep.bedtime_hour}:{bm}")
    if sleep.wake_hour is not None:
        wm = f"{sleep.wake_minute:02d}" if sleep.wake_minute else "00"
        times.append(f"Wake: {sleep.wake_hour}:{wm}")
    if times:
        text += f" | {' / '.join(times)}"
    if sleep.quality:
        text += f" | Quality: {sleep.quality}"
    if sleep.notes:
        text += f" | Notes: {sleep.notes}"
    return [_bullet_block(text)]

async def _build_exercise(exercise: list[ExerciseEntry]) -> list[dict[str, Any]]:
    ex_blocks = []
    for ex in exercise:
        text = (
            f"🏃 Date: {_format_date_only(ex.date)} | {ex.exercise_type.title()} | "
            f"{ex.duration_minutes} mins | Intensity: {ex.intensity}"
        )
        if ex.distance_km:
            text += f" | Distance: {ex.distance_km}km"
        if getattr(ex, "body_parts", None):
            bparts_str = [
                str(getattr(bp, "value", bp)).replace('_', ' ').title() 
                for bp in ex.body_parts
            ]
            text += f" | Body: {', '.join(bparts_str)}"
        if ex.notes:
            text += f" | Notes: {ex.notes}"
        ex_blocks.append(_bullet_block(text))
    return ex_blocks


async def _build_meditation(items: list[MeditationEntry]) -> list[dict]:
    blocks = []
    for s in items:
        dt_str = s.datetime_logged.strftime('%d %B %Y %I:%M%p') if s.datetime_logged else _format_date_only(s.date)
        text = f'🧘 {dt_str} | {s.duration_minutes} mins'
        if s.notes:
            text += f' | {s.notes}'
        blocks.append(_bullet_block(text))
    return blocks

async def _build_cleaning(items: list[CleaningEntry]) -> list[dict]:
    blocks = []
    for s in items:
        dt_str = s.datetime_logged.strftime('%d %B %Y %I:%M%p') if s.datetime_logged else _format_date_only(s.date)
        text = f'🧹 {dt_str} | {s.duration_minutes} mins'
        if s.notes:
            text += f' | {s.notes}'
        blocks.append(_bullet_block(text))
    return blocks

async def _build_sitting(items: list[SittingEntry]) -> list[dict]:
    blocks = []
    for s in items:
        dt_str = s.datetime_logged.strftime('%d %B %Y %I:%M%p') if s.datetime_logged else _format_date_only(s.date)
        text = f'🪷 {dt_str} | {s.duration_minutes} mins'
        if s.took_from:
            text += f' | From: {s.took_from}'
        if s.notes:
            text += f' | {s.notes}'
        blocks.append(_bullet_block(text))
    return blocks

async def _build_group_meditation(items: list[GroupMeditationEntry]) -> list[dict]:
    blocks = []
    for s in items:
        dt_str = s.datetime_logged.strftime('%d %B %Y %I:%M%p') if s.datetime_logged else _format_date_only(s.date)
        text = f'🕊️ {dt_str} | {s.duration_minutes} mins'
        if s.place:
            text += f' | At: {s.place}'
        if s.notes:
            text += f' | {s.notes}'
        blocks.append(_bullet_block(text))
    return blocks

_HABIT_ICONS = {
    "lost_self_control": "🔴",
    "junk_food": "🍔",
    "outside_food": "🛵",
    "late_eating": "🌙",
    "screen_time": "📺",
    "other": "⚠️",
}

async def _build_habits(items: list[HabitEntry]) -> list[dict]:
    blocks = []
    for h in items:
        icon = _HABIT_ICONS.get(h.category, "⚠️")
        dt_str = h.datetime_logged.strftime('%d %B %Y %I:%M%p') if h.datetime_logged else _format_date_only(h.date)
        text = f'{icon} {dt_str} | {h.category.replace("_"," ").title()}: {h.description}'
        if h.notes:
            text += f' | {h.notes}'
        blocks.append(_bullet_block(text))
    return blocks

async def _build_journal(journal_note: str) -> list[dict[str, Any]]:
    text = f"📝 {_get_now_formatted()}: {journal_note}"
    return [{
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }]


_SYNC_CONFIGS = {
    "tasks": SyncConfig(page_id_attr="notion_to_do_page_id", block_builder=_build_tasks),
    "reading_links": SyncConfig(page_id_attr="notion_to_read_page_id", block_builder=_build_links),
    "sleep": SyncConfig(page_id_attr="notion_sleep_page_id", block_builder=_build_sleep),
    "exercise": SyncConfig(page_id_attr="notion_exercise_page_id", block_builder=_build_exercise),
    "meditation": SyncConfig(page_id_attr="notion_meditation_page_id", block_builder=_build_meditation),
    "cleaning": SyncConfig(page_id_attr="notion_cleaning_page_id", block_builder=_build_cleaning),
    "sitting": SyncConfig(page_id_attr="notion_sitting_page_id", block_builder=_build_sitting),
    "group_meditation": SyncConfig(page_id_attr="notion_group_meditation_page_id", block_builder=_build_group_meditation),
    "habits": SyncConfig(page_id_attr="notion_habit_page_id", block_builder=_build_habits),
    "journal_note": SyncConfig(page_id_attr="notion_journal_page_id", block_builder=_build_journal),
}


async def append_notion_blocks(
    tasks: list[TaskItem] | None = None,
    links: list[ReadingLink] | None = None,
    sleep: SleepEntry | None = None,
    exercise: list[ExerciseEntry] | None = None,
    meditation: list[MeditationEntry] | None = None,
    cleaning: list[CleaningEntry] | None = None,
    sitting: list[SittingEntry] | None = None,
    group_meditation: list[GroupMeditationEntry] | None = None,
    habits: list[HabitEntry] | None = None,
    journal_note: str | None = None,
) -> list[str]:
    """Append extracted tasks, links, and wellness data to Notion pages.
    Returns a list of keys that failed to sync."""
    if not settings.enable_notion or not settings.notion_api_key:
        log.info("notion_disabled_or_missing_key")
        return []

    notion = _get_notion()
    failed = []

    entity_map = {
        "tasks": tasks,
        "reading_links": links,
        "sleep": sleep,
        "exercise": exercise,
        "meditation": meditation,
        "cleaning": cleaning,
        "sitting": sitting,
        "group_meditation": group_meditation,
        "habits": habits,
        "journal_note": journal_note,
    }

    for key, config in _SYNC_CONFIGS.items():
        data = entity_map.get(key)
        if data:
            page_id = getattr(settings, config.page_id_attr)
            if not page_id:
                continue
            
            try:
                blocks = await config.block_builder(data)
                await _append_blocks(notion, page_id, blocks)
                log.info(f"notion_{key}_appended")
            except Exception as exc:
                log.error(f"notion_{key}_failed", error=str(exc))
                failed.append(key)

    return failed
