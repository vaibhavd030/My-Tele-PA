"""Input and output guardrail models.

These models define what the guardrail node checks before passing
input to the LLM and before writing output to storage.
"""

import re

from pydantic import BaseModel, field_validator

# Patterns that suggest personally sensitive / off-topic content
_CRISIS_PATTERNS = re.compile(r"\b(suicide|self.harm|kill myself|end it all)\b", re.IGNORECASE)
_INJECTION_PATTERNS = re.compile(
    r"(ignore previous|disregard instructions|system prompt|jailbreak)", re.IGNORECASE
)


class InputGuard(BaseModel):
    """Result of validating a raw user message.

    Attributes:
        is_safe: Whether to proceed with normal processing.
        block_reason: Human-readable reason if blocked.
        detected_crisis: Flag for mental health crisis content.
    """

    raw_text: str
    is_safe: bool = True
    block_reason: str | None = None
    detected_crisis: bool = False

    @field_validator("raw_text")
    @classmethod
    def check_injection(cls, v: str) -> str:
        """Reject prompt injection attempts."""
        if _INJECTION_PATTERNS.search(v):
            raise ValueError("Potential prompt injection detected")
        return v

    def check_crisis(self) -> "InputGuard":
        """Flag crisis content for special handling (do not block)."""
        if _CRISIS_PATTERNS.search(self.raw_text):
            self.detected_crisis = True
        return self
