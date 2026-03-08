import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from life_os.integrations.sqlite_store import save_records, init_db
from life_os.agent.nodes.query import run

async def main():
    try:
        print("Init DB")
        await init_db()
        
        print("Save records")
        await save_records("vaibhav_test", [{
            "date": "2026-03-08",
            "type": "habit",
            "category": "lost_self_control",
            "description": "I got really angry and yelled at my screen.",
            "source": "manual"
        }])
        
        print("Run query")
        state = {
            "user_id": "vaibhav_test",
            "raw_input": "what happened to my self control today?",
        }
        result = await run(state)
        print("Result:", result)
    except Exception as e:
        print("Error:", e)
        raise e

if __name__ == "__main__":
    asyncio.run(main())
