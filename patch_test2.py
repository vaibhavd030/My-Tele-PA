import pytest
import asyncio
from unittest.mock import AsyncMock, patch

async def run_suite():
    import tests.e2e.test_flows as tf
    pytest.main(["-v", "-s", "tests/e2e/test_flows.py"])

if __name__ == "__main__":
    asyncio.run(run_suite())
