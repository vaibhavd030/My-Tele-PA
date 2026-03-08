"""Centralised OpenAI client factory."""

from functools import lru_cache
from typing import Any

import instructor
from openai import AsyncOpenAI

from life_os.config.settings import settings


def calculate_cost(usage: Any) -> tuple[int, float]:
    """Calculate token count and estimated cost for a given usage response."""
    if not usage:
        return 0, 0.0
    tokens = getattr(usage, "total_tokens", 0)
    prompt_tokens = getattr(usage, "prompt_tokens", 0)
    completion_tokens = getattr(usage, "completion_tokens", 0)
    # Costs based on gpt-4o-mini
    cost_usd = (prompt_tokens * 0.15 / 1_000_000) + (completion_tokens * 0.60 / 1_000_000)
    return tokens, cost_usd


@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())


@lru_cache(maxsize=1)
def get_instructor_client() -> instructor.AsyncInstructor:
    # We use mode=instructor.Mode.JSON for robust extraction
    return instructor.from_openai(get_openai_client(), mode=instructor.Mode.JSON)
