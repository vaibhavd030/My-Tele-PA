"""Query node to answer questions about historical data using Text2SQL."""

import datetime as dt
import json
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from pydantic import BaseModel

from life_os.agent.state import AgentState
from life_os.config.clients import calculate_cost, get_instructor_client, get_openai_client
from life_os.config.settings import settings
from life_os.integrations.bigquery_store import get_db

log = structlog.get_logger(__name__)


class SQLQuery(BaseModel):
    query: str
    explanation: str


SCHEMA_PROMPT = """
Table: `{project_id}.{dataset_id}.records` (id STRING, user_id STRING, date DATE, type STRING, data JSON, source STRING)
Types and their JSON fields:
- sleep: duration_hours (float), bedtime_hour (int), wake_hour (int), quality (int 1-10)
- exercise: exercise_type (str), duration_minutes (int), distance_km (float), intensity (int), body_parts (list)
- meditation: duration_minutes (int), datetime_logged (ISO str)
- cleaning: duration_minutes (int), datetime_logged (ISO str)
- sitting: duration_minutes (int), took_from (str), datetime_logged (ISO str)
- group_meditation: duration_minutes (int), place (str), datetime_logged (ISO str)
- habit: category (str: lost_self_control|junk_food|outside_food|late_eating|screen_time|other), description (str)
- tasks: task (str), priority (int 1-3)
- journal_note: note (str)

Use JSON_EXTRACT_SCALAR(data, '$.field') for JSON fields. Cast to INT64 or FLOAT64 before using SUM/AVG.
CRITICAL INSTRUCTION: If the user asks "how much I have slept in the last X days", they often want the "AVG" per day if X > 1. Use AVG() instead of SUM() for sleep. When filtering by date, use "date >= DATE_SUB(PARSE_DATE('%Y-%m-%d', '{today}'), INTERVAL X DAY)" strictly.
ALWAYS FILTER OUT TEST DATA: ensure your query includes `WHERE (JSON_EXTRACT_SCALAR(data, '$.is_test') != 'true' OR JSON_EXTRACT_SCALAR(data, '$.is_test') IS NULL)`.
Today's date is: {today}
"""


async def run(state: AgentState) -> dict[str, Any]:
    """Generate a SQL query for the user's question, execute, and format the response."""
    user_id = state["user_id"]
    query_text = state["raw_input"]

    log.info("querying_historical_data", user_id=user_id)

    instructor_client = get_instructor_client()
    tokens1, cost1 = 0, 0.0
    
    target_tz = ZoneInfo(settings.timezone)
    today_iso = dt.datetime.now(target_tz).replace(microsecond=0).isoformat()
    
    # Format prompt variables
    formatted_prompt = SCHEMA_PROMPT.format(
        project_id=settings.gcp_project_id,
        dataset_id=settings.bq_dataset_id,
        today=today_iso.split('T')[0]
    )
    
    try:
        sql_response, raw_1 = await instructor_client.chat.completions.create_with_completion(
            model=settings.openai_model,
            response_model=SQLQuery,
            messages=[
                {"role": "system", "content": formatted_prompt},
                {
                    "role": "user",
                    "content": f"User ID is '{user_id}'. Generate a BigQuery standard SQL query for: {query_text}",
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
    client = get_db()
    try:
        if not sql_query.strip().upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed.")
            
        results_iterator = client.query(sql_query).result()
        
        results = []
        for r in results_iterator:
            results.append(dict(r.items()))
            
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
