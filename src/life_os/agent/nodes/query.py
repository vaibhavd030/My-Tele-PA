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
    try:
        # For a personal bot we can just pull all recent rows to pandas
        # In a massive dataset we'd want SQL filtering, but pandas in-memory 
        # is nice for ~1000s of rows
        cursor = await db.execute(
            "SELECT date, type, data FROM records WHERE user_id = ? ORDER BY date DESC LIMIT 300", 
            (user_id,)
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    if not rows:
        return {"response_message": "I don't have any data logged for you yet!"}

    # 2. Process into a pandas DataFrame to make it readable
    parsed_rows = []
    for r in rows:
        try:
            row_dict = dict(r)
            data_dict = json.loads(row_dict["data"])
            parsed_rows.append(data_dict)
        except Exception as exc:
            log.warning("failed_to_parse_row", error=str(exc))
            
    if not parsed_rows:
        return {"response_message": "I don't have any parseable data logged for you yet!"}
            
    df = pd.DataFrame(parsed_rows)
    # Convert to markdown for LLM to read easily
    data_markdown = df.to_markdown(index=False)
    
    # Optional: If df is huge, we might only send relevant columns or head()/tail()
    # But for a personal OS, 30-100 rows in markdown is ~1000 tokens which 
    # GPT-4o handles flawlessly.

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
                )
            },
            {"role": "user", "content": query_text},
        ]
    )

    answer = response.choices[0].message.content or "Sorry, I couldn't analyze the data."
    
    return {"response_message": answer}
