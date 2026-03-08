import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from life_os.integrations.sqlite_store import get_db, init_db

async def main():
    db = await get_db()
    
    query1 = "SELECT SUM(json_extract(data, '$.duration_hours')) AS total_sleep_hours FROM records WHERE user_id = 'vaibhav_test' AND type = 'sleep' AND date >= date('now', '-1 days')"
    
    query2 = "SELECT date, json_extract(data, '$.duration_hours') FROM records WHERE user_id = 'vaibhav_test' AND type = 'sleep'"
    
    print("Testing Query 1 (LLM Generated):")
    cursor = await db.execute(query1)
    rows = await cursor.fetchall()
    print([dict(r) for r in rows])
    
    print("Testing Query 2 (All Sleep):")
    cursor = await db.execute(query2)
    rows = await cursor.fetchall()
    print([dict(r) for r in rows])
    
    await db.close()

if __name__ == "__main__":
    asyncio.run(main())
