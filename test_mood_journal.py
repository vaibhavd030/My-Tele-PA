import asyncio
from langchain_core.messages import HumanMessage
from life_os.agent.graph import get_app
from unittest.mock import patch

@patch("life_os.agent.nodes.persister.save_records")
async def main(mock_save):
    agent = await get_app()
    print("Testing mood + journal extraction logic...\n")
    
    config = {"configurable": {"thread_id": "test_mood_journal"}}
    inputs = {
        "messages": [HumanMessage(content="I was waiting for an offer from New day however after five round they have rejected me feeling a bit sad but that's fine")],
        "user_id": "test_verification",
        "raw_input": "I was waiting for an offer from New day however after five round they have rejected me feeling a bit sad but that's fine"
    }

    async for chunk in agent.astream(inputs, config, stream_mode="values"):
        if "response_message" in chunk and chunk["response_message"]:
             print(f"\nFinal Response:\n{chunk['response_message']}")
             break

if __name__ == "__main__":
    asyncio.run(main())
