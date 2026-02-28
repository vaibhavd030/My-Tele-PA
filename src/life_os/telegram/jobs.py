"""Telegram scheduler jobs for daily check-ins and weekly digests."""

import json
from datetime import datetime, timedelta

import pandas as pd
import structlog
from openai import AsyncOpenAI
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from life_os.config.settings import settings
from life_os.integrations.sqlite_store import get_db

log = structlog.get_logger(__name__)
client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())


async def send_morning_checkin(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a proactive 8 AM daily check-in message."""
    if not context.job or not context.job.chat_id:
        return
    chat_id = int(context.job.chat_id)
    message = (
        "Good morning! ☀️\nHow did you sleep last night? Any big plans or exercises for today?"
    )
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML)
    log.info("sent_morning_checkin", chat_id=chat_id)


async def send_weekly_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Query the last 7 days of SQLite data, ask LLM to aggregate, and send a summary."""
    if not context.job or not context.job.chat_id:
        return
    chat_id = int(context.job.chat_id)
    user_id = str(chat_id)

    db = await get_db()
    try:
        seven_days_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
        cursor = await db.execute(
            "SELECT date, type, data FROM records "
            "WHERE user_id = ? AND date >= ? ORDER BY date DESC",
            (user_id, seven_days_ago),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    if not rows:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "It's time for your weekly digest! 📊\n"
                "But it looks like you haven't logged any data this week. "
                "Let's start tracking next week!"
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    parsed_rows = []
    for r in rows:
        try:
            row_dict = dict(r)
            data_dict = json.loads(row_dict["data"])
            parsed_rows.append(data_dict)
        except Exception as exc:
            log.warning("failed_to_parse_row", error=str(exc))

    df = pd.DataFrame(parsed_rows)
    data_markdown = df.to_markdown(index=False)

    prompt = (
        "You are a supportive, enthusiastic Life OS assistant. Summarize the user's past "
        "7 days of wellness/exercise/sleep data into a highly engaging, visually appealing "
        "weekly digest Telegram message using HTML parse format (e.g. <b>bold</b>, <i>italic</i>, "
        "completely avoid markdown asterisks like **bold**). Highlight notable streaks, "
        "average sleep, exercise completed, and end with an encouraging note.\n\n"
        f"Data:\n{data_markdown}"
    )

    response = await client.chat.completions.create(
        model=settings.openai_model, temperature=0.3, messages=[{"role": "user", "content": prompt}]
    )

    summary = response.choices[0].message.content or "Weekly digest failed to generate."

    await context.bot.send_message(chat_id=chat_id, text=summary, parse_mode=ParseMode.HTML)
    log.info("sent_weekly_digest", chat_id=chat_id)
