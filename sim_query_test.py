import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from life_os.integrations.sqlite_store import save_records, init_db
from life_os.agent.nodes.query import run

async def main():
    print("Initializing DB...")
    await init_db()
    
    print("Saving records...")
    await save_records("vaibhav_test", [
        {"date": "2026-03-07", "type": "sleep", "duration_hours": 5.5, "bedtime_hour": 1, "wake_hour": 6},
        {"date": "2026-03-08", "type": "sleep", "duration_hours": 8.0, "bedtime_hour": 23, "wake_hour": 7},
        {"date": "2026-03-08", "type": "sleep", "duration_hours": 4.75, "bedtime_hour": 0, "wake_hour": 5, "quality": 7}
    ])
    
    queries = [
        "How much I have slept in last 24 hours?",
        "How much I have slept in last two days?"
    ]
    
    for q in queries:
        try:
            print(f"\n--- Query: {q} ---")
            state = {
                "user_id": "vaibhav_test",
                "raw_input": q,
                "entities": {},
                "missing_fields": [],
                "clarification_count": 0,
                "abort": False,
            }
            print("Before run(state)")
            result = await run(state)
            print("After run(state), Result:", result)
        except Exception as e:
            print("EXCEPTION CAUGHT IN LOOP:", e)
            import traceback
            traceback.print_exc()

    print("END OF MAIN")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print("EXCEPTION CAUGHT IN MAIN:", e)
    print("PYTHON SCRIPT EXITING")
