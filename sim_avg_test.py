import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from life_os.integrations.sqlite_store import save_records, init_db
from life_os.agent.nodes.query import run

async def main():
    await init_db()
    
    await save_records("vaibhav_test2", [
        {"date": "2026-03-07", "type": "sleep", "duration_hours": 5.0},
        {"date": "2026-03-08", "type": "sleep", "duration_hours": 8.0},
        {"date": "2026-03-08", "type": "sleep", "duration_hours": 4.0}
    ])
    
    queries = [
        "What is my average sleep duration in the last two days?",
        "Average my sleep duration for the last 2 days"
    ]
    
    for q in queries:
        try:
            print(f"\n--- Query: {q} ---")
            state = {
                "user_id": "vaibhav_test2",
                "raw_input": q,
                "entities": {},
                "missing_fields": [],
                "clarification_count": 0,
                "abort": False,
            }
            result = await run(state)
            print("Result:", result)
        except Exception as e:
            print("EXCEPTION CAUGHT IN LOOP:", e)

if __name__ == "__main__":
    asyncio.run(main())
