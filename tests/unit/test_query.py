import json
import pytest
from types import SimpleNamespace

from life_os.agent.nodes.query import run
from life_os.integrations.bigquery_store import get_db, init_db, save_records




@pytest.mark.asyncio
async def test_query_node_has_data(base_state, mocker):
    await init_db()
    
    mocker.patch(
        "life_os.agent.nodes.query.get_openai_client",
        return_value=mocker.AsyncMock(
            chat=mocker.AsyncMock(
                completions=mocker.AsyncMock(
                    create=mocker.AsyncMock(
                        return_value=mocker.Mock(
                            choices=[mocker.Mock(message=mocker.Mock(content="Here is your summary."))],
                            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10)
                        )
                    )
                )
            )
        )
    )
    mocker.patch(
        "life_os.agent.nodes.query.get_instructor_client",
        return_value=mocker.AsyncMock(
            chat=mocker.AsyncMock(
                completions=mocker.AsyncMock(
                    create_with_completion=mocker.AsyncMock(
                        return_value=(
                            mocker.Mock(query="SELECT * FROM records", explanation="Test"),
                            mocker.Mock(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10))
                        )
                    )
                )
            )
        )
    )

    # Insert dummy data to satisfy the sqlite read in query.py
    user_id = base_state["user_id"]
    await save_records(user_id, [
        {"type": "exercise", "date": "2026-03-05", "duration_minutes": 30}
    ])
    
    state = base_state.copy()
    state["raw_input"] = "How much did I exercise?"
    
    result = await run(state)
    
    assert "response_message" in result
    assert "Here is your summary." in result["response_message"]

@pytest.mark.asyncio
async def test_query_node_no_data(base_state, mocker):
    await init_db()
    
    mocker.patch(
        "life_os.agent.nodes.query.get_openai_client",
        return_value=mocker.AsyncMock(
            chat=mocker.AsyncMock(
                completions=mocker.AsyncMock(
                    create=mocker.AsyncMock(
                        return_value=mocker.Mock(
                            choices=[mocker.Mock(message=mocker.Mock(content="I don't have any data logged for you yet!"))],
                            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10)
                        )
                    )
                )
            )
        )
    )
    mocker.patch(
        "life_os.agent.nodes.query.get_instructor_client",
        return_value=mocker.AsyncMock(
            chat=mocker.AsyncMock(
                completions=mocker.AsyncMock(
                    create_with_completion=mocker.AsyncMock(
                        return_value=(
                            mocker.Mock(query="SELECT * FROM records", explanation="Test"),
                            mocker.Mock(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10))
                        )
                    )
                )
            )
        )
    )
    
    state = base_state.copy()
    state["raw_input"] = "How much did I exercise?"
    
    result = await run(state)
    
    assert "response_message" in result
    assert "I don't have any data logged for you yet!" in result["response_message"]
