import pytest

from life_os.agent.nodes.persister import run
from life_os.integrations.sqlite_store import init_db


@pytest.fixture(autouse=True)
def mock_dbs(mocker, tmp_path):
    import life_os.integrations.sqlite_store as store
    db_path = str(tmp_path / "persister_test.db")
    mocker.patch("life_os.config.settings.settings.db_path", db_path)
    
    # We don't want to actually hit Notion during unit tests
    mocker.patch("life_os.integrations.notion_store.append_notion_blocks", return_value=[])
    yield
    store._connection = None


@pytest.mark.asyncio
async def test_persister_no_entities(base_state):
    state = base_state.copy()
    result = await run(state)
    
    assert result["response_message"] == "No data extracted to save."


@pytest.mark.asyncio
async def test_persister_with_missing_fields(base_state):
    await init_db()
    state = base_state.copy()
    from datetime import date
    state["entities"] = {"sleep": {"date": date.today().isoformat(), "duration_hours": 8.0, "quality": None}}
    
    result = await run(state)
    
    assert "sleep" in str(result["response_message"]).lower() or "logged" in str(result["response_message"]).lower()


@pytest.mark.asyncio
async def test_persister_success(base_state, mocker):
    await init_db()
    # Mock LLM to return a success message
    mocker.patch(
        "life_os.config.clients.get_openai_client",
        return_value=mocker.AsyncMock(
            chat=mocker.AsyncMock(
                completions=mocker.AsyncMock(
                    create=mocker.AsyncMock(
                        return_value=mocker.Mock(
                            choices=[mocker.Mock(message=mocker.Mock(content="Got it, saved your tasks!"))]
                        )
                    )
                )
            )
        )
    )

    state = base_state.copy()
    state["entities"] = {"tasks": [{"task": "Buy milk", "priority": 2}]}
    state["missing_fields"] = []
    
    result = await run(state)
    
    assert "saved your task" in result["response_message"].lower() or "got it" in result["response_message"].lower() or "logged" in result["response_message"].lower()
    assert "structured_records" in result
    assert len(result["structured_records"]) == 1
    assert result["structured_records"][0]["type"] == "tasks"
