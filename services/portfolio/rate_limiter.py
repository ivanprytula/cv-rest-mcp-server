from collections.abc import Callable
from ipaddress import ip_address

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from services.portfolio.settings import settings


def get_client_ip(request: Request) -> str:
    """Resolve the rate-limit key according to the configured client-IP strategy.

    Order: X-Forwarded-For entry (if client_ip_xff_entry > 0), then the raw
    client_ip_header, then the socket peer address.
    """
    if settings.client_ip_xff_entry > 0:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            entries = [entry.strip() for entry in xff.split(",")]
            if len(entries) >= settings.client_ip_xff_entry:
                return entries[-settings.client_ip_xff_entry]
    if settings.client_ip_header:
        value = request.headers.get(settings.client_ip_header.lower())
        if value:
            return value.strip()
    return get_remote_address(request)


def peer_is_loopback(request: Request) -> bool:
    """Whether the *socket peer* (trusted, not header-derived) is loopback.

    Used for dev exemptions: loopback peers bypass rate limits and can never be
    dynamically banned. Header-derived IPs are deliberately ignored here — they
    are attacker-controllable behind a proxy.
    """
    client = request.scope.get("client")
    if not client or not client[0]:
        return False
    try:
        return ip_address(client[0]).is_loopback
    except ValueError:
        return False


def _exempt_loopback(request: Request) -> bool:
    # Behind a trusted proxy the socket peer is a local hop, not the client;
    # exempting it would disarm every limit, so exemptions only apply to
    # direct peers (local dev).
    return not settings.trust_proxy and peer_is_loopback(request)


limiter = Limiter(key_func=get_client_ip)


def limits(*limit_values: str) -> Callable:
    """Stack multiple rate limits on one endpoint, with service-wide exemptions.

    Every limit shares the same evaluation pass (slowapi registers all limits
    under the endpoint's name) and exempts loopback peers.
    """

    def decorator(func):
        for value in reversed(limit_values):
            func = limiter.limit(value, exempt_when=_exempt_loopback)(func)
        return func

    return decorator
