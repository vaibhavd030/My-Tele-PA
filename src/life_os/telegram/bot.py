"""Telegram Bot Application Entrypoint.

Handles incoming messages and routes them to the LangGraph agent.
Supports both long-polling and webhook setups.
"""

import argparse

import structlog
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from life_os.agent.graph import app as agent_app
from life_os.config.logging import configure_logging
from life_os.config.settings import settings
from life_os.integrations.sqlite_store import init_db

log = structlog.get_logger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("Hello! I am your Life OS agent. How can I help you today?")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    user_id = str(update.message.from_user.id) if update.message.from_user else "unknown"

    # Authorized user check
    if update.message.chat_id != settings.telegram_chat_id:
        log.warning(
            "unauthorized_access_attempt",
            chat_id=update.message.chat_id,
            user_id=user_id,
            hint="Add this chat_id to TELEGRAM_CHAT_ID in .env",
        )
        await update.message.reply_text("Unauthorized access.")
        return

    text = update.message.text
    structlog.contextvars.bind_contextvars(user_id=user_id, message_id=update.message.message_id)

    log.info("processing_message", length=len(text))

    # Invoke LangGraph app with thread configuration for memory checkpointer
    config = {"configurable": {"thread_id": user_id}}

    state = await agent_app.ainvoke(
        {
            "user_id": user_id,
            "raw_input": text,
        },
        config=config,
    )

    response = state.get("response_message")
    if not response:
        response = "Noted."

    from telegram.constants import ParseMode

    await update.message.reply_text(response, parse_mode=ParseMode.HTML)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["polling", "webhook"], default="polling")
    args = parser.parse_args()

    configure_logging()

    # Initialize SQLite database
    import asyncio

    asyncio.run(init_db())

    log.info("starting_bot", mode=args.mode)

    application = (
        Application.builder().token(settings.telegram_bot_token.get_secret_value()).build()
    )

    # ── JobQueue Schedulers ──
    from datetime import time

    from life_os.telegram.jobs import send_morning_checkin, send_weekly_digest

    chat_id = settings.telegram_chat_id
    if chat_id:
        from zoneinfo import ZoneInfo

        target_tz = ZoneInfo(settings.timezone)

        if application.job_queue:
            # 8 AM daily
            t_morning = time(hour=settings.morning_checkin_hour, minute=0, tzinfo=target_tz)
            application.job_queue.run_daily(send_morning_checkin, time=t_morning, chat_id=chat_id)

            # Sunday 7 PM weekly
            # python-telegram-bot run_daily days parameter: integer tuple
            # (0-6, where 0=Monday, 6=Sunday)
            t_weekly = time(hour=19, minute=0, tzinfo=target_tz)
            application.job_queue.run_daily(
                send_weekly_digest, time=t_weekly, days=(6,), chat_id=chat_id
            )

    # ── Handlers ──
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if args.mode == "polling":
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    else:
        # Webhook setup logic goes here for cloudrun
        application.run_webhook(listen="0.0.0.0", port=8080, url_path="webhook")  # noqa: S104


if __name__ == "__main__":
    main()
