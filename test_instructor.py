import asyncio
from unittest.mock import AsyncMock
import instructor
client = AsyncMock()
inst = instructor.from_openai(client, mode=instructor.Mode.JSON)
print("INST:", inst)
