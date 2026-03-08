"""Telegram scheduler jobs for daily check-ins and weekly digests."""

import json
from datetime import datetime, timedelta

import pandas as pd
import structlog
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from life_os.config.clients import get_openai_client
from life_os.config.settings import settings
from life_os.integrations.bigquery_store import get_db

log = structlog.get_logger(__name__)


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

    from google.cloud import bigquery
    db = get_db()
    seven_days_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
    
    query = f"""
        SELECT date, type, data FROM `{settings.gcp_project_id}.{settings.bq_dataset_id}.records`
        WHERE user_id = @user_id AND date >= PARSE_DATE('%Y-%m-%d', @seven_days_ago)
        ORDER BY date DESC
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("seven_days_ago", "STRING", seven_days_ago),
        ]
    )
    
    try:
        results = db.query(query, job_config=job_config).result()
        rows = list(results)
    except Exception as exc:
        log.error("weekly_digest_query_failed", error=str(exc))
        rows = []

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

    response = await get_openai_client().chat.completions.create(
        model=settings.openai_model, temperature=0.3, messages=[{"role": "user", "content": prompt}]
    )

    summary = response.choices[0].message.content or "Weekly digest failed to generate."

    await context.bot.send_message(chat_id=chat_id, text=summary, parse_mode=ParseMode.HTML)
    log.info("sent_weekly_digest", chat_id=chat_id)
