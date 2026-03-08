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

@pytest.fixture(autouse=True)
def mock_bigquery_client(mocker):
    """Globally mock Google Cloud BigQuery client to prevent DefaultCredentialsError in tests."""
    
    # Mock Secrets to prevent NoneType client init
    mocker.patch("life_os.config.settings.settings.openai_api_key", mocker.Mock(get_secret_value=lambda: "test-key"))
    mocker.patch("life_os.config.settings.settings.telegram_bot_token", mocker.Mock(get_secret_value=lambda: "test-bot"))

    # Crucial: LRU caches evaluated before tests run return None. Clear them!
    from life_os.config.clients import get_openai_client, get_instructor_client
    get_openai_client.cache_clear()
    get_instructor_client.cache_clear()

    # Mock GCP Auth
    mocker.patch("google.auth.default", return_value=(mocker.Mock(), "test-project"))
    
    class MockResult:
        def __init__(self, data=None):
            self.data = data or []
        def __iter__(self):
            return iter(self.data)
        def items(self):
            for i in self.data:
                yield i

    class MockJob:
        def __init__(self, data=None):
            self.data = data or []
        def result(self):
            return MockResult(self.data)

    class MockClient:
        def insert_rows_json(self, table, rows):
            return []
        def query(self, query, job_config=None):
            return MockJob([{"duration_hours": 8, "quality": 10}])
        def get_dataset(self, dataset_id):
            return True
        def get_table(self, table_id):
            return True

    mocker.patch("google.cloud.bigquery.Client", return_value=MockClient())
    mocker.patch("life_os.integrations.bigquery_store.get_db", return_value=MockClient())
    mocker.patch("life_os.config.settings.settings.gcp_project_id", "test-project")
    mocker.patch("life_os.config.settings.settings.bq_dataset_id", "test_dataset")
    mocker.patch("life_os.integrations.bigquery_store.init_db", return_value=None)
