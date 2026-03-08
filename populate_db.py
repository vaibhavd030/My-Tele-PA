import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from life_os.integrations.sqlite_store import save_records

async def main():
    await save_records("test_user", [{
        "date": "2026-03-08",
        "type": "habit",
        "source": "manual",
        "category": "lost_self_control",
        "description": "I got angry at a coworker and shouted."
    }])

if __name__ == "__main__":
    asyncio.run(main())
