from unittest.mock import MagicMock

from slowapi.util import get_remote_address

from app.rate_limiter import limiter


def test_limiter_exists():
    assert limiter is not None


def test_client_ip_from_remote_addr():
    request = MagicMock()
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "203.0.113.5"
    assert get_remote_address(request) == "203.0.113.5"


def test_client_ip_fallback_when_no_client():
    request = MagicMock()
    request.headers = {}
    request.client = None
    assert get_remote_address(request) == "127.0.0.1"


def test_limiter_uses_remote_address():
    assert limiter._key_func is get_remote_address
