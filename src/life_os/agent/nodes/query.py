"""Query node to answer questions about historical data using Text2SQL."""

import json
from typing import Any

import structlog
from pydantic import BaseModel

from life_os.agent.state import AgentState
from life_os.config.clients import get_instructor_client, get_openai_client, calculate_cost
from life_os.config.settings import settings
from life_os.integrations.sqlite_store import get_db

log = structlog.get_logger(__name__)


class SQLQuery(BaseModel):
    query: str
    explanation: str


SCHEMA_PROMPT = """
Table: records (id, user_id, date, type, data JSON)
Types: sleep, exercise, wellness, tasks, journal_note
JSON fields vary by type. Generate a SQLite query.
"""


async def run(state: AgentState) -> dict[str, Any]:
    """Generate a SQL query for the user's question, execute, and format the response."""
    user_id = state["user_id"]
    query_text = state["raw_input"]

    log.info("querying_historical_data", user_id=user_id)

    instructor_client = get_instructor_client()
    tokens1, cost1 = 0, 0.0
    try:
        sql_response, raw_1 = await instructor_client.chat.completions.create_with_completion(
            model=settings.openai_model,
            response_model=SQLQuery,
            messages=[
                {"role": "system", "content": SCHEMA_PROMPT},
                {
                    "role": "user",
                    "content": f"User ID is '{user_id}'. Generate a query for: {query_text}",
                },
            ],
        )
        tokens1, cost1 = calculate_cost(raw_1.usage)
        sql_query = sql_response.query
        log.info("generated_sql_query", query=sql_query, explanation=sql_response.explanation)
    except Exception as exc:
        log.error("failed_to_generate_sql", error=str(exc))
        return {"response_message": "Sorry, I couldn't formulate a query for that."}

    # Execute SQL
    db = await get_db()
    try:
        if not sql_query.strip().upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed.")
            
        cursor = await db.execute(sql_query)
        rows = await cursor.fetchall()
        
        results = []
        for r in rows:
            results.append(dict(r))
            
    except Exception as exc:
        log.error("failed_to_execute_sql", error=str(exc), query=sql_query)
        return {"response_message": "Sorry, I ran into an issue retrieving the data."}

    if not results:
        data_json = "No results found for this query."
    else:
        data_json = json.dumps(results, indent=2, default=str)

    # 3. Ask LLM to answer the user's query based on the results
    response = await get_openai_client().chat.completions.create(
        model=settings.openai_model,
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful life OS assistant. Answer the user's question "
                    "based ONLY on the following query results in JSON format. "
                    "Be concise, friendly, and use formatting. If the data doesn't "
                    "contain the answer, say so.\n\n"
                    f"Query Results:\n{data_json}"
                ),
            },
            {"role": "user", "content": query_text},
        ],
    )
    tokens2, cost2 = calculate_cost(response.usage)

    answer = response.choices[0].message.content or "Sorry, I couldn't analyze the data."

    return {
        "response_message": answer,
        "total_tokens": tokens1 + tokens2,
        "total_cost_usd": cost1 + cost2,
    }
