"""Simulation file to run the full workflow locally and display output."""

import asyncio
import json
import os
from datetime import date

import structlog

# Set a readable console logging format for the simulation
os.environ["LOG_FORMAT"] = "console"
os.environ["LOG_LEVEL"] = "WARNING"

from life_os.agent.graph import app as agent_app
from life_os.config.logging import configure_logging
from life_os.integrations.sqlite_store import init_db, get_db


async def run_simulation():
    configure_logging()
    
    print("\n" + "="*50)
    print("TELE_PA v2.0 - LOCAL WORKFLOW SIMULATION")
    print("="*50 + "\n")
    
    print("[1] Initializing local SQLite database...")
    await init_db()
    print("✅ Database initialized at ./data/life_os.db\n")
    
    user_id = "sim_user_123"
    messages = [
        "I slept for 5 hours and did a few mins of meditation",
        "Just ran 5k in 30 minutes! Feeling great.",
        "Add a note: Buy groceries tomorrow.",
        "Based on my history, what is my average run duration?"
    ]
    
    print("[2] Running test messages through the Agent Graph:\n")
    
    for i, msg in enumerate(messages, 1):
        print("-" * 40)
        print(f"📩 Message {i}: '{msg}'")
        print("-" * 40)
        
        print(f"⚙️  Graph Execution Started...")
        state = await agent_app.ainvoke(
            {
                "user_id": user_id,
                "raw_input": msg,
                "entities": {},
                "missing_fields": [],
                "clarification_count": 0,
                "abort": False,
                "response_message": None,
                "structured_records": [],
            },
            config={"configurable": {"thread_id": "sim_thread_1"}}
        )
        
        print(f"🤖 Agent Response:\n{state.get('response_message', 'No response.')}\n")
        
    print("[3] Verifying SQLite Database Contents:\n")
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM records WHERE user_id = ?", (user_id,))
        rows = await cursor.fetchall()
        
        print(f"Found {len(rows)} records in the database:")
        for r in rows:
            record_dict = dict(r)
            data_preview = json.loads(record_dict["data"])
            print(f"   • Type: {record_dict['type']}, Date: {record_dict['date']}, Data: {data_preview}")
    finally:
        await db.close()

    print("\n" + "="*50)
    print("SIMULATION COMPLETE")
    print("="*50 + "\n")


if __name__ == "__main__":
    asyncio.run(run_simulation())
