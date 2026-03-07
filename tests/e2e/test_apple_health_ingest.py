import pytest
from fastapi.testclient import TestClient
from life_os.telegram.bot import create_fastapi_app
from life_os.config.settings import settings

app = create_fastapi_app()
client = TestClient(app)

@pytest.fixture(autouse=True)
def mock_dependencies(mocker):
    mocker.patch("life_os.telegram.bot.save_if_not_duplicate", return_value=True)
    mocker.patch("life_os.telegram.bot.append_notion_blocks", return_value=[])
    # Set the token for stability
    settings.apple_health_token = "test_token_123"

def test_apple_health_ingest_auth_failure():
    response = client.post("/api/apple-health/ingest", json={"data": {}})
    assert response.status_code == 401

def test_apple_health_ingest_success():
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "sleep_analysis",
                    "data": [
                        {
                            "date": "2026-03-01T23:30:00Z",
                            "qty": 7.5
                        }
                    ]
                }
            ]
        }
    }
    response = client.post(
        "/api/apple-health/ingest", 
        json=payload,
        headers={"Authorization": "Bearer test_token_123"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "records_saved": 1}
