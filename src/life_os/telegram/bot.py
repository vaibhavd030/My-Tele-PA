"""Telegram Bot Application Entrypoint.

Handles incoming messages and routes them to the LangGraph agent.
Supports both long-polling and webhook setups.
"""

import argparse
from typing import Any

import structlog
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from life_os.agent.graph import get_app
from life_os.config.logging import configure_logging
from life_os.config.settings import settings
from life_os.integrations.sqlite_store import init_db
from life_os.models.wellness import SleepEntry

log = structlog.get_logger(__name__)


def _infer_quality(qty_hours: float) -> int:
    if qty_hours >= 7.5: return 10
    if qty_hours >= 6.5: return 8
    if qty_hours >= 5.5: return 6
    if qty_hours >= 4.0: return 4
    return 2

def parse_apple_health_sleep(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse Health Auto Export JSON payload into SleepEntry-compatible dicts."""
    from datetime import datetime
    records = []
    metrics = payload.get('data', {}).get('metrics', [])
    for metric in metrics:
        if metric.get('name') != 'sleep_analysis':
            continue
        for data_point in metric.get('data', []):
            start = datetime.fromisoformat(data_point['date'])
            qty = data_point.get('qty', 0)
            records.append({
                'type': 'sleep',
                'date': start.date().isoformat(),
                'source': 'apple_health',
                'bedtime_hour': start.hour,
                'bedtime_minute': start.minute,
                'duration_hours': round(qty, 2),
                'quality': _infer_quality(qty),
            })
    return records


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

    agent_app = await get_app()

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


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming voice notes by transcribing them to text and passing to the agent."""
    if not update.message or not (update.message.voice or update.message.audio):
        return

    user_id = str(update.message.from_user.id) if update.message.from_user else "unknown"

    if update.message.chat_id != settings.telegram_chat_id:
        log.warning(
            "unauthorized_voice_access_attempt",
            chat_id=update.message.chat_id,
            user_id=user_id,
        )
        await update.message.reply_text("Unauthorized access.")
        return

    attachment = update.message.voice or update.message.audio
    # 1. duration check - up to 20 minutes (1200s)
    if attachment.duration > 1200:
        await update.message.reply_text("Voice note too long. Max 20 minutes allowed.")
        return

    status_msg = await update.message.reply_text("🎙️ Transcribing...")

    import io

    from tenacity import retry, stop_after_attempt, wait_exponential

    from life_os.config.clients import get_openai_client

    # 2. Download to memory and check bounds
    file_info = await context.bot.get_file(attachment.file_id)
    if file_info.file_size and file_info.file_size > 25 * 1024 * 1024:
        await status_msg.edit_text("File too large for transcription API (max 25MB).")
        return

    buffer = io.BytesIO()
    await file_info.download_to_memory(out=buffer)
    buffer.name = f"voice_{update.message.message_id}.ogg"

    # 3. Transcribe with Whisper inside a retry block mapping API failures
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _transcribe() -> Any:
        # Using whisper-1 for standard OpenAI STT compatibility.
        return await get_openai_client().audio.transcriptions.create(
            model="whisper-1",
            file=buffer,
            language="en",
            prompt=(
                "wellness, exercise, Heartfulness, Notion, pomodoro, habit tracking, "
                "gym, sleep, diet"
            ),
        )
    
    try:
        transcript = await _transcribe()
    except Exception as exc:
        log.error("transcription_failed", error=str(exc))
        await status_msg.edit_text("Failed to transcribe voice note.")
        return

    text = transcript.text.strip()
    if not text:
        await status_msg.edit_text("Could not transcribe any speech from that note.")
        return

    # 4. Preview edit reflection
    preview = text[:100] + "..." if len(text) > 100 else text
    await status_msg.edit_text(f"🎙️ Heard: \"{preview}\"\nProcessing...")

    structlog.contextvars.bind_contextvars(user_id=user_id, message_id=update.message.message_id)
    log.info("processing_voice_message", length=len(text))

    # 5. Execute agent workflow exactly alongside text requests mapped 
    config = {"configurable": {"thread_id": user_id}}
    agent_app = await get_app()
    state = await agent_app.ainvoke(
        {
            "user_id": user_id,
            "raw_input": text,
            "input_modality": "voice",
            "voice_file_id": attachment.file_id
        },
        config=config,
    )

    from telegram.constants import ParseMode
    response = state.get("response_message") or "Noted."
    await status_msg.edit_text(f"🎙️ Heard: \"{preview}\"\n\n{response}", parse_mode=ParseMode.HTML)


from fastapi import FastAPI, Request, Response, HTTPException
from life_os.integrations.sqlite_store import save_if_not_duplicate
from life_os.integrations.notion_store import append_notion_blocks

def create_fastapi_app(application: Application | None = None) -> FastAPI:
    app = FastAPI(title="Life OS Agent Webhook")

    @app.post("/webhook")
    async def telegram_webhook(request: Request) -> Response:
        if application is None:
            return Response(status_code=500)
        update = Update.de_json(data=await request.json(), bot=application.bot)
        await application.process_update(update)
        return Response(status_code=200)

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}
        
    @app.post("/api/apple-health/ingest")
    async def ingest_apple_health(request: Request) -> dict[str, Any]:
        """Receive Apple Health data from Health Auto Export app."""
        auth = request.headers.get('Authorization')
        if auth != f'Bearer {settings.apple_health_token}':
            raise HTTPException(status_code=401)
        payload = await request.json()
        records = parse_apple_health_sleep(payload)
        
        saved_count = 0
        if records:
            for record in records:
                user_id = str(settings.telegram_chat_id)
                is_new = await save_if_not_duplicate(user_id, record)
                if is_new:
                    saved_count += 1
                    sleep_entry = SleepEntry(**record)
                    await append_notion_blocks(sleep=sleep_entry)
                    
        return {'status': 'ok', 'records_saved': saved_count}

    return app


def _run_migrations() -> None:
    import alembic.command
    import alembic.config
    import sqlalchemy as sa
    from sqlalchemy.engine import create_engine
    from life_os.config.settings import settings
    import os
    
    # 1) Connect directly to check if Alembic tracked the schema
    engine = create_engine(f"sqlite:///{settings.db_path}")
    insp = sa.inspect(engine)
    has_records = insp.has_table("records")
    has_alembic = insp.has_table("alembic_version")
    
    alembic_cfg = alembic.config.Config("alembic.ini")
    
    if has_records and not has_alembic:
        # V1/V2 legacy database detected mapping to the volume!
        # Stamp it as 'head' to prevent Alembic from trying to re-create `records`
        alembic.command.stamp(alembic_cfg, "head")
        log.info("legacy_db_detected_stamped_alembic_head")
    else:
        alembic.command.upgrade(alembic_cfg, "head")
        log.info("schema_migrations_applied_successfully")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["polling", "webhook"], default="polling")
    args = parser.parse_args()

    configure_logging()

    # Initialize SQLite database via Alembic strictly
    try:
        _run_migrations()
    except Exception as e:
        log.error("migration_failed", error=str(e))
        raise

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
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    if args.mode == "polling":
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    else:
        log.info("starting_fastapi_webhook_server")
        import os

        import uvicorn
        
        app = create_fastapi_app(application)

        async def run_fastapi() -> None:
            
            # 2. Wire webhook integration dynamically
            webhook_url = settings.webhook_url
            if webhook_url:
                await application.bot.set_webhook(url=f"{webhook_url.rstrip('/')}/webhook")
            
            port = int(os.environ.get("PORT", 8080))
            config = uvicorn.Config(app, host="0.0.0.0", port=port)  # noqa: S104
            server = uvicorn.Server(config)
            
            async with application:
                await application.start()
                await server.serve()
                await application.stop()

        asyncio.run(run_fastapi())


if __name__ == "__main__":
    main()
