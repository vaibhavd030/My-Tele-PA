"""Google Cloud BigQuery integration for logging metrics and analytics.

This module will replace SQLite as the primary data store, using BQ standard SQL
and real-time streaming inserts for Notion/Sheets synchronization.
"""

import json
from datetime import UTC
from typing import Any

import structlog
from google.cloud import bigquery
from google.cloud.exceptions import NotFound

from life_os.config.settings import settings

log = structlog.get_logger(__name__)

# Reusing the existing SQLite structure logic for BQ Table Definitions
SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("user_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("type", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("data", "JSON", mode="REQUIRED"),
    bigquery.SchemaField("source", "STRING", mode="REQUIRED"),
]

_bq_client: bigquery.Client | None = None

def get_db() -> bigquery.Client:
    """Get or instantiate the global BigQuery client."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=settings.gcp_project_id)
    return _bq_client

async def init_db() -> None:
    """Initialize the BigQuery Dataset and Table if they do not exist."""
    client = get_db()
    dataset_id = f"{settings.gcp_project_id}.{settings.bq_dataset_id}"
    
    # 1. Ensure Dataset
    try:
        client.get_dataset(dataset_id)
    except NotFound:
        dataset = bigquery.Dataset(dataset_id)
        dataset.location = "us-central1"
        client.create_dataset(dataset, timeout=30)
        log.info("bigquery_dataset_created", id=dataset_id)
        
    table_id = f"{dataset_id}.records"
    
    # 2. Ensure Table
    try:
        client.get_table(table_id)
        log.info("bigquery_table_detected", id=table_id)
    except NotFound:
        table = bigquery.Table(table_id, schema=SCHEMA)
        client.create_table(table, timeout=30)
        log.info("bigquery_table_created", id=table_id)


async def save_records(user_id: str, records: list[dict[str, Any]]) -> None:
    """Save records directly to BigQuery."""
    import uuid
    from _datetime import datetime as dt
    if not records:
        return
        
    client = get_db()
    table_id = f"{settings.gcp_project_id}.{settings.bq_dataset_id}.records"
    
    rows_to_insert = []
    for r in records:
        record_type = r.get("type", "unknown")
        record_date = r.get("date", dt.now(UTC).date().isoformat())
        record_source = r.get("source", "telegram")
        
        # Clone without routing metadata
        data_payload = dict(r)
        data_payload.pop("type", None)
        data_payload.pop("date", None)
        data_payload.pop("source", None)

        rows_to_insert.append({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "date": record_date,
            "type": record_type,
            "data": json.dumps(data_payload),
            "source": record_source
        })

    errors = client.insert_rows_json(table_id, rows_to_insert)
    if errors:
        log.error("bigquery_insert_errors", errors=errors)
        raise RuntimeError(f"BigQuery Insert Failed: {errors}")
        
    log.info("saved_records_to_bigquery", count=len(records), user_id=user_id)


async def save_if_not_duplicate(user_id: str, record: dict[str, Any]) -> bool:
    """Used for Apple Health sync deduplication in webhook.
    Returns True if actually saved, False if skipped.
    """
    client = get_db()
    r_type = record.get("type")
    r_date = record.get("date")
    r_source = record.get("source")
    
    if not all([r_type, r_date, r_source]):
        return False
        
    query = f"""
        SELECT id FROM `{settings.gcp_project_id}.{settings.bq_dataset_id}.records`
        WHERE user_id = @user_id 
          AND type = @type 
          AND date = PARSE_DATE('%Y-%m-%d', @date)
          AND source = @source
        LIMIT 1
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("type", "STRING", r_type),
            bigquery.ScalarQueryParameter("date", "STRING", r_date),
            bigquery.ScalarQueryParameter("source", "STRING", r_source),
        ]
    )
    
    results = client.query(query, job_config=job_config).result()
    if len(list(results)) > 0:
        log.info("duplicate_record_skipped", user_id=user_id, type=r_type, date=r_date)
        return False
        
    await save_records(user_id, [record])
    return True


async def get_current_streak(user_id: str) -> int:
    """Calculate the current consecutive daily streak using BigQuery Standard SQL window functions."""
    client = get_db()
    
    query = f"""
        WITH daily_logs AS (
            SELECT DISTINCT date 
            FROM `{settings.gcp_project_id}.{settings.bq_dataset_id}.records`
            WHERE user_id = @user_id AND type != 'system'
        ),
        numbered_days AS (
            SELECT 
                date,
                DATE_DIFF(date, '2000-01-01', DAY) as day_num,
                ROW_NUMBER() OVER (ORDER BY date) as row_num
            FROM daily_logs
        ),
        streak_groups AS (
            SELECT 
                date,
                day_num - row_num AS group_id
            FROM numbered_days
        ),
        streaks AS (
            SELECT 
                group_id,
                COUNT(*) as streak_length,
                MAX(date) as last_activity_date
            FROM streak_groups
            GROUP BY group_id
        )
        SELECT streak_length
        FROM streaks
        WHERE last_activity_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        ORDER BY last_activity_date DESC
        LIMIT 1
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
        ]
    )
    
    try:
        results = list(client.query(query, job_config=job_config).result())
        if not results:
            return 0
        return results[0].streak_length
    except Exception as e:
        log.error("streak_calculation_failed", error=str(e))
        return 0
