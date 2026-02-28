"""Intent classifier to route messages between logging data and querying history."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import instructor
import structlog
from openai import AsyncOpenAI
from pydantic import BaseModel

from life_os.agent.state import AgentState
from life_os.config.settings import settings

log = structlog.get_logger(__name__)

client = instructor.from_openai(AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value()))


class Intent(StrEnum):
    LOG = "log"
    QUERY = "query"
    OTHER = "other"


class MessageIntent(BaseModel):
    intent: Intent


async def run(state: AgentState) -> dict[str, Any]:
    """Classify intent of the message."""
    log.info("classifying_intent", user_id=state["user_id"])

    text = state["raw_input"]

    classification = await client.chat.completions.create(
        model=settings.openai_model,
        response_model=MessageIntent,
        temperature=0.0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Classify the user's message into one of three intents:\n"
                    "- 'log': The user is sharing anything about their day, health, mood, "
                    "activities, plans, food, work, journal entries, tasks, links, or anything "
                    "they did, felt, or are planning to do. When in doubt, choose 'log'.\n"
                    "- 'query': The user is asking a question about their past tracked data. "
                    "e.g. 'how did I sleep this week?', 'show me my exercise log'.\n"
                    "- 'other': Truly unrelated — e.g. asking for help with maths, news, "
                    "random facts, technical questions with no personal wellness context."
                ),
            },
            {"role": "user", "content": text},
        ],
    )

    return {"intent": classification.intent.value}
