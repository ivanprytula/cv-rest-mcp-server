import threading
import time
from collections import deque
from ipaddress import ip_address

from app.settings import settings


class ViolationTracker:
    """In-memory fail2ban-lite: repeated rate-limit violations trigger a
    temporary ban for the offending client key.

    Single-process only (matches the in-memory slowapi storage); state resets
    on restart. Strikes and bans are pruned lazily on access.
    """

    def __init__(
        self,
        *,
        threshold: int,
        window_seconds: int,
        ban_seconds: int,
        max_tracked: int = 10000,
    ) -> None:
        self._threshold = threshold
        self._window_seconds = window_seconds
        self._ban_seconds = ban_seconds
        self._max_tracked = max_tracked
        self._lock = threading.Lock()
        self._strikes: dict[str, deque[float]] = {}
        self._banned_until: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return self._threshold > 0

    def record(self, client_ip: str, *, now: float | None = None) -> None:
        if not self.enabled or not client_ip or _is_loopback(client_ip):
            return
        now = now if now is not None else time.monotonic()
        with self._lock:
            strikes = self._strikes.setdefault(client_ip, deque())
            strikes.append(now)
            while strikes and strikes[0] < now - self._window_seconds:
                strikes.popleft()
            if len(strikes) >= self._threshold:
                self._banned_until[client_ip] = now + self._ban_seconds
                del self._strikes[client_ip]
            self._trim(now)

    def is_banned(self, client_ip: str, *, now: float | None = None) -> bool:
        if not self.enabled or not client_ip or _is_loopback(client_ip):
            return False
        now = now if now is not None else time.monotonic()
        with self._lock:
            until = self._banned_until.get(client_ip)
            if until is None:
                return False
            if until <= now:
                del self._banned_until[client_ip]
                return False
            return True

    def ban_remaining_seconds(self, client_ip: str, *, now: float | None = None) -> int:
        now = now if now is not None else time.monotonic()
        with self._lock:
            return max(0, int(self._banned_until.get(client_ip, 0) - now))

    def _trim(self, now: float) -> None:
        """Bound memory: expire stale strikes, then drop oldest entries over cap."""
        for ip in list(self._strikes):
            strikes = self._strikes[ip]
            while strikes and strikes[0] < now - self._window_seconds:
                strikes.popleft()
            if not strikes:
                del self._strikes[ip]
        while len(self._strikes) + len(self._banned_until) > self._max_tracked:
            oldest = next(iter(self._strikes), None)
            if oldest is None:
                break
            del self._strikes[oldest]


def _is_loopback(ip_str: str) -> bool:
    try:
        return ip_address(ip_str).is_loopback
    except ValueError:
        return False


violation_tracker = ViolationTracker(
    threshold=settings.failban_threshold,
    window_seconds=settings.failban_window_seconds,
    ban_seconds=settings.failban_ban_seconds,
    max_tracked=settings.failban_max_tracked,
)


def register_violation_from_request(request) -> None:
    """Record a rate-limit violation for the resolved client, skipping
    loopback peers (dev traffic must never self-ban)."""
    from app.rate_limiter import get_client_ip, peer_is_loopback

    if peer_is_loopback(request):
        return
    violation_tracker.record(get_client_ip(request))
