import pytest
from life_os.integrations.bigquery_store import init_db
import life_os.agent.graph as graph
import asyncio

async def test_debug():
    graph._app = None
    app = await graph.get_app()
    initial_state = {
        "user_id": "e2e_user_2",
        "raw_input": "I went to the gym for 45 mins today.",
        "chat_history": [],
    }
    config = {"configurable": {"thread_id": "test_e2e_clarification"}}
    res = await app.ainvoke(initial_state, config)
    print("KEYS:", res.keys())
    print("ENTITIES:", res.get("entities"))
    print("MISSING:", res.get("missing_fields"))

asyncio.run(test_debug())
