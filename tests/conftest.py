import pytest


@pytest.fixture()
def base_state() -> dict:
    """Minimal agent state for extractor tests."""
    return {
        "user_id": "test_user",
        "raw_input": "",
        "entities": {},
        "clarification_count": 0,
    }
