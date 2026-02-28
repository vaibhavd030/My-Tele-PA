"""Query node to answer questions about historical data using pandas."""

import json
from typing import Any

import pandas as pd
import structlog
from openai import AsyncOpenAI

from life_os.agent.state import AgentState
from life_os.config.settings import settings
from life_os.integrations.sqlite_store import get_db

log = structlog.get_logger(__name__)
client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())


async def run(state: AgentState) -> dict[str, Any]:
    """Fetch user's data into pandas, build a context string, and answer their query."""
    user_id = state["user_id"]
    query_text = state["raw_input"]

    log.info("querying_historical_data", user_id=user_id)

    # 1. Fetch data from SQLite
    db = await get_db()
    summaries = []
    try:
        for record_type in ["sleep", "exercise", "wellness", "tasks", "journal_note"]:
            cursor = await db.execute(
                "SELECT data FROM records WHERE user_id=? AND type=?"
                " ORDER BY date DESC LIMIT 30",
                (user_id, record_type),
            )
            rows = await cursor.fetchall()
            if rows:
                parsed = []
                for r in rows:
                    try:
                        parsed.append(json.loads(dict(r)["data"]))
                    except Exception as exc:
                        log.warning("failed_to_parse_row", error=str(exc))
                if parsed:
                    df = pd.DataFrame(parsed)
                    summaries.append(
                        f"## {record_type.upper()} (last {len(parsed)} entries)\n"
                        + df.to_markdown(index=False)
                    )
    finally:
        await db.close()

    if not summaries:
        return {"response_message": "I don't have any data logged for you yet!"}

    data_markdown = "\n\n".join(summaries)

    # 3. Ask LLM to answer the user's query based on the dataframe markdown
    response = await client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful life OS assistant. Answer the user's question "
                    "based ONLY on the following historical data logs in markdown format. "
                    "Be concise, friendly, and use formatting. If the data doesn't "
                    "contain the answer, say so.\n\n"
                    f"Data Logs:\n{data_markdown}"
                ),
            },
            {"role": "user", "content": query_text},
        ],
    )

    answer = response.choices[0].message.content or "Sorry, I couldn't analyze the data."

    return {"response_message": answer}
