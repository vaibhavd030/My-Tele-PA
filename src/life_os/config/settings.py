"""Application settings — loaded from environment variables.

Usage:
    from life_os.config.settings import settings
    print(settings.openai_api_key)
"""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # All application configuration, loaded from .env or environment.

    # Required (must be set):
    #    telegram_bot_token: Bot token from @BotFather.
    #    openai_api_key: OpenAI API key.

    # Optional integrations (disabled by default):
    #    enable_notion: If True, also writes to Notion databases.
    #    enable_gcal: If True, also creates Google Calendar events.

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Required ──────────────────────────────────────────────────────────
    telegram_bot_token: SecretStr = Field(description="Telegram bot token from @BotFather")
    openai_api_key: SecretStr = Field(description="OpenAI API key")
    telegram_chat_id: int = Field(description="Your personal Telegram chat ID")

    # ── SQLite (primary store — always enabled) ────────────────────────
    db_path: str = Field(default="./data/life_os.db")

    # ── Optional: Notion ──────────────────────────────────────────────────
    enable_notion: bool = Field(default=False)
    notion_api_key: SecretStr | None = Field(default=None)
    notion_sleep_page_id: str | None = Field(default=None)
    notion_exercise_page_id: str | None = Field(default=None)
    notion_wellness_page_id: str | None = Field(default=None)
    notion_journal_page_id: str | None = Field(default=None)
    notion_to_do_page_id: str | None = Field(default=None)
    notion_to_read_page_id: str | None = Field(default=None)

    # ── Optional: Google Calendar ─────────────────────────────────────────
    enable_gcal: bool = Field(default=False)
    google_credentials_path: str = Field(default="./config/credentials.json")
    google_calendar_id: str = Field(default="primary")

    # ── LLM ────────────────────────────────────────────────────────────────
    openai_model: str = Field(default="gpt-4o-mini")  # Cheapest, sufficient
    openai_temperature: float = Field(default=0.1, ge=0.0, le=2.0)

    # ── App ────────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="console")  # 'console' | 'json'
    morning_checkin_hour: int = Field(default=8, ge=0, le=23)
    weekly_report_day: str = Field(default="sun")
    max_clarification_turns: int = Field(default=3)

    @field_validator("openai_model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        """Ensure only supported OpenAI models are configured."""
        allowed = {"gpt-4o-mini", "gpt-4o", "gpt-4-turbo"}
        if v not in allowed:
            raise ValueError(f"Model {v!r} not in allowed set {allowed}")
        return v


settings = Settings()  # Module-level singleton
