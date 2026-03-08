import pytest

from life_os.agent.nodes.classifier import run


@pytest.mark.asyncio
async def test_classifier_log_intent(base_state, mocker):
    mocker.patch(
        "life_os.config.clients.get_instructor_client",
        return_value=mocker.AsyncMock(
            chat=mocker.AsyncMock(
                completions=mocker.AsyncMock(
                    create_with_completion=mocker.AsyncMock(
                        return_value=(
                            mocker.Mock(intent=mocker.Mock(value="log")),
                            mocker.Mock(usage=mocker.Mock(total_tokens=10, prompt_tokens=5, completion_tokens=5))
                        )
                    )
                )
            )
        ),
    )
    
    state = base_state.copy()
    state["raw_input"] = "I ran 5k today."
    
    result = await run(state)
    assert result["intent"] == "log"


@pytest.mark.asyncio
async def test_classifier_query_intent(base_state, mocker):
    mocker.patch(
        "life_os.config.clients.get_instructor_client",
        return_value=mocker.AsyncMock(
            chat=mocker.AsyncMock(
                completions=mocker.AsyncMock(
                    create_with_completion=mocker.AsyncMock(
                        return_value=(
                            mocker.Mock(intent=mocker.Mock(value="query")),
                            mocker.Mock(usage=mocker.Mock(total_tokens=10, prompt_tokens=5, completion_tokens=5))
                        )
                    )
                )
            )
        ),
    )
    
    state = base_state.copy()
    state["raw_input"] = "Show my exercises from last week."
    
    result = await run(state)
    assert result["intent"] == "query"


@pytest.mark.asyncio
async def test_classifier_other_intent(base_state, mocker):
    mocker.patch(
        "life_os.config.clients.get_instructor_client",
        return_value=mocker.AsyncMock(
            chat=mocker.AsyncMock(
                completions=mocker.AsyncMock(
                    create_with_completion=mocker.AsyncMock(
                        return_value=(
                            mocker.Mock(intent=mocker.Mock(value="other")),
                            mocker.Mock(usage=mocker.Mock(total_tokens=10, prompt_tokens=5, completion_tokens=5))
                        )
                    )
                )
            )
        ),
    )
    
    state = base_state.copy()
    state["raw_input"] = "Hello how are you?"
    
    result = await run(state)
    assert result["intent"] == "other"
