"""Input and output guardrail models.

These models define what the guardrail node checks before passing
input to the LLM and before writing output to storage.
"""

from pydantic import BaseModel


class SafetyClassification(BaseModel):
    """Result of classifying a raw user message for safety.

    Attributes:
        is_injection: Whether this is a prompt injection attempt.
        is_crisis: Flag for mental health crisis content.
        reasoning: Brief reasoning for the classification.
    """

    is_injection: bool
    is_crisis: bool
    reasoning: str
