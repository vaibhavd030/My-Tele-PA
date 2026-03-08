"""Input and output guardrail models.

These models define what the guardrail node checks before passing
input to the LLM and before writing output to storage.
"""

from pydantic import BaseModel


class SafetyClassification(BaseModel):
    """Result of classifying a raw user message for safety.

    Attributes:
        is_injection: Whether this is a prompt injection attempt.
        reasoning: Brief reasoning for the classification.
    """

    is_injection: bool
    reasoning: str
