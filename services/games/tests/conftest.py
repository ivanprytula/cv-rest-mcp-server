import os


os.environ.update(
    {
        # Disable geo guards so tests run predictably
        "FAILBAN_THRESHOLD": "0",
        "TRUST_PROXY": "false",
        "CLIENT_IP_XFF_ENTRY": "0",
        # Must not leak the developer's real local .env value (used to point
        # "Back to portfolio" at http://localhost:8080 in dev) — tests assert
        # the same-origin default (empty = bare "/" link).
        "PORTFOLIO_BASE_URL": "",
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
