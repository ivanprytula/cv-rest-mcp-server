from unittest.mock import MagicMock

from slowapi.util import get_remote_address

from app.rate_limiter import get_client_ip, limiter
from app.settings import settings


def _request(headers=None, host="203.0.113.5"):
    request = MagicMock()
    request.headers = headers or {}
    request.client = MagicMock()
    request.client.host = host
    return request


def test_limiter_exists():
    assert limiter is not None


def test_client_ip_from_remote_addr():
    assert get_remote_address(_request()) == "203.0.113.5"


def test_client_ip_fallback_when_no_client():
    request = _request()
    request.client = None
    assert get_remote_address(request) == "127.0.0.1"


def test_default_strategy_uses_socket_peer(monkeypatch):
    monkeypatch.setattr(settings, "client_ip_xff_entry", 0)
    monkeypatch.setattr(settings, "client_ip_header", "")
    assert get_client_ip(_request()) == "203.0.113.5"


def test_client_ip_header_strategy(monkeypatch):
    monkeypatch.setattr(settings, "client_ip_xff_entry", 0)
    monkeypatch.setattr(settings, "client_ip_header", "X-Real-IP")
    request = _request(headers={"x-real-ip": "198.51.100.7"})
    assert get_client_ip(request) == "198.51.100.7"


def test_client_ip_header_falls_back_to_socket_when_missing(monkeypatch):
    monkeypatch.setattr(settings, "client_ip_xff_entry", 0)
    monkeypatch.setattr(settings, "client_ip_header", "X-Real-IP")
    assert get_client_ip(_request()) == "203.0.113.5"


def test_xff_entry_counted_from_right(monkeypatch):
    monkeypatch.setattr(settings, "client_ip_xff_entry", 2)
    monkeypatch.setattr(settings, "client_ip_header", "")
    request = _request(headers={"x-forwarded-for": "spoofed, 198.51.100.7, 10.0.0.1"})
    assert get_client_ip(request) == "198.51.100.7"


def test_xff_entries_are_whitespace_stripped(monkeypatch):
    monkeypatch.setattr(settings, "client_ip_xff_entry", 1)
    monkeypatch.setattr(settings, "client_ip_header", "")
    request = _request(headers={"x-forwarded-for": " 198.51.100.7 "})
    assert get_client_ip(request) == "198.51.100.7"


def test_xff_falls_back_to_socket_when_chain_too_short(monkeypatch):
    monkeypatch.setattr(settings, "client_ip_xff_entry", 3)
    monkeypatch.setattr(settings, "client_ip_header", "")
    request = _request(headers={"x-forwarded-for": "only, two"})
    assert get_client_ip(request) == "203.0.113.5"


def test_limiter_uses_get_client_ip_key_func():
    assert limiter._key_func is get_client_ip
