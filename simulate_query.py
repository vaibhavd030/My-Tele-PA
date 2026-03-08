import asyncio
import os
import sys

# Ensure imports work from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from life_os.agent.nodes.query import run
from life_os.agent.state import AgentState

async def main():
    state = {
        "user_id": "test_user",
        "raw_input": "what happened when I lost my self control?",
    }
    result = await run(state)
    print("Result:", result)

if __name__ == "__main__":
    asyncio.run(main())
