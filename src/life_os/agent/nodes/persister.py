"""Persistence Node

Saves any extracted entity data to long-term storage (SQLite/Notion).
"""

from typing import Any

import structlog

from life_os.agent.state import AgentState
from life_os.integrations.notion_store import append_notion_blocks
from life_os.integrations.sqlite_store import save_records

log = structlog.get_logger(__name__)


async def run(state: AgentState) -> dict[str, Any]:
    """Save extracted entities to the database."""
    user_id = state["user_id"]
    entities = state.get("entities", {})

    if not entities:
        return {"response_message": "No data extracted to save."}

    records_to_save = []
    response_parts = ["I have logged the following:"]

    for entity_type, entity_obj in entities.copy().items():
        if not entity_obj:
            continue

        if entity_type in ("tasks", "reading_links"):
            # Handled below
            continue

        items_to_process = entity_obj if isinstance(entity_obj, list) else [entity_obj]

        for item in items_to_process:
            if hasattr(item, "model_dump"):
                record_dump = item.model_dump(exclude_none=True)
            else:
                record_dump = {"value": item}

            record_dump["type"] = entity_type
            records_to_save.append(record_dump)

            # Create a simple summary for the user
            formatted_fields = []
            for k, v in record_dump.items():
                if k == "type":
                    continue
                # Remove datetime.date etc wrappers from display
                display_val = str(v)
                formatted_fields.append(f"{k.replace('_', ' ').capitalize()}: {display_val}")

            fields_str = ", ".join(formatted_fields)
            response_parts.append(f"- <b>{entity_type.title()}</b>: {fields_str}")

    # Extract specific lists for Notion routing
    notion_tasks = entities.pop("tasks", [])
    notion_links = entities.pop("reading_links", [])
    # Also grab sleep, exercise, and wellness for Notion, but keep them for SQLite too
    sleep = entities.get("sleep")
    exercise = entities.get("exercise")
    wellness = entities.get("wellness")
    journal_note = entities.get("journal_note")

    if notion_tasks or notion_links or sleep or exercise or wellness or journal_note:
        failed_syncs = await append_notion_blocks(
            tasks=notion_tasks,
            links=notion_links,
            sleep=sleep,
            exercise=exercise,
            wellness=wellness,
            journal_note=journal_note,
        )
        if not failed_syncs:
            response_parts.append("✨ Synced your data directly to Notion!")
        else:
            response_parts.append(
                f"⚠️ Synced to Notion, but failed to sync: {', '.join(failed_syncs)}"
            )

    if records_to_save:
        await save_records(user_id=user_id, records=records_to_save)

    final_response = "\n".join(response_parts)

    # Critical: Wipe the entities out of memory so they don't get merged into the next chat turns!
    return {
        "structured_records": records_to_save,
        "response_message": final_response,
        "entities": {},
    }
