import os


os.environ.update(
    {
        # Disable geo/time guards so tests run predictably
        "SERVICE_HOURS_START": "",
        "SERVICE_HOURS_END": "",
        "SERVICE_DAYS": "",
        "SERVICE_TIMEZONE": "",
        "ALLOWED_IPS": "",
        "BLOCKED_IPS": "",
        "FAILBAN_THRESHOLD": "0",
        "TRUST_PROXY": "false",
        "CLIENT_IP_XFF_ENTRY": "0",
        "CLIENT_IP_HEADER": "",
    }
)
os.environ.pop("ALLOWED_IPS_FILE", None)
os.environ.pop("BLOCKED_IPS_FILE", None)

import pytest
from httpx import ASGITransport, AsyncClient

from services.games.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as ac:
        yield ac
