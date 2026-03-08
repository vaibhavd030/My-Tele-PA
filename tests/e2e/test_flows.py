import pytest

from life_os.integrations.bigquery_store import init_db


@pytest.fixture(autouse=True)
def mock_dbs(mocker):
    import life_os.integrations.bigquery_store as store
    
    mocker.patch("life_os.integrations.bigquery_store.init_db", return_value=None)
    mocker.patch("life_os.integrations.bigquery_store.save_records", return_value=None)
    mocker.patch("life_os.config.settings.settings.gcp_project_id", "test-project")
    mocker.patch("life_os.config.settings.settings.bq_dataset_id", "test_dataset")
    
    # We do not hit Notion in E2E
    mocker.patch("life_os.integrations.notion_store.append_notion_blocks", return_value=[])
    
    yield

@pytest.fixture(autouse=True)
async def _mock_memory_saver():
    """Use an in-memory saver for tests to prevent asyncio SQLite locks hanging."""
    import life_os.agent.graph as graph
    from langgraph.checkpoint.memory import MemorySaver
    memory = MemorySaver()
    graph._app = graph.builder.compile(checkpointer=memory)
    yield
    graph._app = None


@pytest.mark.asyncio
async def test_e2e_successful_extraction(mocker):
    import life_os.agent.graph as graph
    
    await init_db()
    
    app = graph._app
    config = {"configurable": {"thread_id": "test_e2e_1"}}
    
    # Needs a functional LLM mockup matching instructor + standard OpenAI
    mocker.patch(
        "life_os.config.clients.get_openai_client",
        return_value=mocker.AsyncMock(
            chat=mocker.AsyncMock(
                completions=mocker.AsyncMock(
                    create=mocker.AsyncMock(
                        return_value=mocker.Mock(
                            choices=[
                                mocker.Mock(
                                    message=mocker.Mock(
                                        content="Here is a nice confirmation summary"
                                    )
                                )
                            ]
                        )
                    )
                )
            )
        )
    )
    
    from life_os.agent.nodes.extractor import ExtractedData
    from life_os.models.wellness import SleepEntry
    
    mocker.patch(
        "life_os.agent.nodes.classifier.get_instructor_client",
        return_value=mocker.AsyncMock(
            chat=mocker.AsyncMock(
                completions=mocker.AsyncMock(
                    create_with_completion=mocker.AsyncMock(
                        return_value=(
                            mocker.Mock(intent=mocker.Mock(value="log")),
                            mocker.Mock(usage=mocker.Mock(
                                total_tokens=10, prompt_tokens=5, completion_tokens=5
                            ))
                        )
                    )
                )
            )
        )
    )

    mocker.patch(
        "life_os.agent.nodes.extractor._call_llm",
        return_value=(ExtractedData(
                            sleep=SleepEntry(
                                date="2026-03-05", # type: ignore
                                bedtime_hour=23,
                                bedtime_minute=0,
                                wake_hour=6,
                                wake_minute=30,
                                duration_hours=7.5, 
                                quality=10
                            ),
                            exercise=[],
                            wellness=None,
                            tasks=[],
                            reading_links=[],
                        ), 150, 0.002)
        )

    
    initial_state = {
        "user_id": "e2e_user_1",
        "raw_input": "I slept beautifully for 8 hours.",
        "chat_history": [],
    }
    
    result = await app.ainvoke(initial_state, config)
    
    print("FINAL STATE RESULT:", result)
    
    records = result.get("structured_records", [])
    assert any(r.get("type") == "sleep" for r in records)
    assert any(r.get("duration_hours") == 7.5 for r in records if r.get("type") == "sleep")
    assert result["response_message"] != ""
    assert not result.get("missing_fields")

@pytest.mark.asyncio
async def test_e2e_clarification_flow(mocker):
    import life_os.agent.graph as graph
    
    await init_db()
    
    app = graph._app
    config = {"configurable": {"thread_id": "test_e2e_clarification"}}
    
    mocker.patch(
        "life_os.config.clients.get_openai_client",
        return_value=mocker.AsyncMock(
            chat=mocker.AsyncMock(
                completions=mocker.AsyncMock(
                    create=mocker.AsyncMock(
                        return_value=mocker.Mock(
                            choices=[
                                mocker.Mock(
                                    message=mocker.Mock(
                                        content="Here is a clarification prompt."
                                    )
                                )
                            ]
                        )
                    )
                )
            )
        )
    )
    
    from life_os.agent.nodes.extractor import ExtractedData
    from life_os.models.wellness import ExerciseEntry
    
    mocker.patch(
        "life_os.agent.nodes.classifier.get_instructor_client",
        return_value=mocker.AsyncMock(
            chat=mocker.AsyncMock(
                completions=mocker.AsyncMock(
                    create_with_completion=mocker.AsyncMock(
                        return_value=(
                            mocker.Mock(intent=mocker.Mock(value="log")),
                            mocker.Mock(usage=mocker.Mock(
                                total_tokens=10, prompt_tokens=5, completion_tokens=5
                            ))
                        )
                    )
                )
            )
        )
    )

    mocker.patch(
        "life_os.agent.nodes.extractor._call_llm",
        return_value=(ExtractedData(
                            sleep=None,
                            exercise=[ExerciseEntry(
                                date="2026-03-05", # type: ignore
                                exercise_type="gym",
                                body_parts=None, # Missing explicit body parts
                                duration_minutes=45
                            )],
                            wellness=None,
                            tasks=[],
                            reading_links=[],
                        ), 120, 0.001)
        )

    
    initial_state = {
        "user_id": "e2e_user_2",
        "raw_input": "I went to the gym for 45 mins today.",
        "chat_history": [],
    }
    
    result = await app.ainvoke(initial_state, config)
    
    assert "exercise" in result["entities"]
    assert "body part" in result["missing_fields"]
    assert "body part(s) did you train" in result["response_message"]
    assert result["clarification_count"] == 1
