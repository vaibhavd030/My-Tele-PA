import json
import pytest

from life_os.integrations.sqlite_store import get_db, init_db, save_records


@pytest.fixture(autouse=True)
def sqlite_test_db(mocker, tmp_path):
    import life_os.integrations.sqlite_store as store
    db_path = str(tmp_path / "test.db")
    mocker.patch("life_os.config.settings.settings.db_path", db_path)
    yield db_path
    store._connection = None



@pytest.mark.asyncio
async def test_sqlite_roundtrip():
    await init_db()
    
    user_id = "test_user_123"
    records = [
        {"type": "exercise", "date": "2026-03-05", "duration_minutes": 30},
        {"type": "sleep", "date": "2026-03-05", "duration_hours": 8.0},
    ]
    
    await save_records(user_id, records)
    
    db = await get_db()
    cursor = await db.execute("SELECT * FROM records ORDER BY type ASC")
    rows = await cursor.fetchall()
    
    assert len(rows) == 2
    
    ex_row = rows[0]
    slp_row = rows[1]
    
    assert ex_row["type"] == "exercise"
    assert ex_row["user_id"] == user_id
    assert ex_row["date"] == "2026-03-05"
    assert json.loads(ex_row["data"])["duration_minutes"] == 30
    
    assert slp_row["type"] == "sleep"
    assert slp_row["user_id"] == user_id
    assert slp_row["date"] == "2026-03-05"
    assert json.loads(slp_row["data"])["duration_hours"] == 8.0
    
    await db.close()
