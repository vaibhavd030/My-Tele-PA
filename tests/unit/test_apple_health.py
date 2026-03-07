import pytest
from life_os.telegram.bot import parse_apple_health_sleep
from life_os.models.wellness import SleepEntry

def test_parse_apple_health_sleep():
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "sleep_analysis",
                    "data": [
                        {
                            "date": "2026-03-01T23:30:00Z",
                            "qty": 7.5
                        },
                        {
                            "date": "2026-03-02T22:15:00Z",
                            "qty": 6.0
                        }
                    ]
                },
                {
                    "name": "step_count",
                    "data": [
                        {"qty": 5000}
                    ]
                }
            ]
        }
    }
    
    records = parse_apple_health_sleep(payload)
    
    assert len(records) == 2
    
    r1 = records[0]
    assert r1["type"] == "sleep"
    assert r1["date"] == "2026-03-01"
    assert r1["source"] == "apple_health"
    assert r1["duration_hours"] == 7.5
    assert r1["quality"] == 10
    assert r1["bedtime_hour"] == 23
    assert r1["bedtime_minute"] == 30
    
    # Ensure it maps directly to Pydantic models gracefully
    s1 = SleepEntry(**r1)
    assert s1.duration_hours == 7.5
    assert s1.quality == 10
