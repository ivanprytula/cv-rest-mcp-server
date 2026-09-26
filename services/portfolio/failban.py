import threading
import time
from collections import deque
from ipaddress import ip_address

from services.portfolio.settings import settings


class ViolationTracker:
    """In-memory fail2ban-lite: repeated rate-limit violations trigger a
    temporary ban for the offending client key.

    Strikes pool per client, so misbehaviour spread across many routes still
    accumulates toward the threshold. The resulting ban is *scoped to the paths
    that actually tripped it*: a client that only overran the PDF limit keeps
    browsing the HTML CV. An unattributable strike (no resolvable path) bans
    every path, so an un-scopable offender is never let through.

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
        # client -> deque[(recorded_at, path | None)]
        self._strikes: dict[str, deque[tuple[float, str | None]]] = {}
        self._banned_until: dict[str, float] = {}
        # client -> offending paths, or None when the ban covers every path
        self._banned_paths: dict[str, frozenset[str] | None] = {}

    @property
    def enabled(self) -> bool:
        return self._threshold > 0

    def record(
        self, client_ip: str, path: str | None = None, *, now: float | None = None
    ) -> None:
        """Count one rate-limit violation for `client_ip`, scoped to `path`."""
        if not self.enabled or not client_ip or _is_loopback(client_ip):
            return
        now = now if now is not None else time.monotonic()
        scope = path or None
        with self._lock:
            strikes = self._strikes.setdefault(client_ip, deque())
            strikes.append((now, scope))
            while strikes and strikes[0][0] < now - self._window_seconds:
                strikes.popleft()
            if len(strikes) >= self._threshold:
                recorded = [recorded_path for _, recorded_path in strikes]
                # A strike with no path can't be attributed to a route, so the
                # ban widens to every path rather than leaving a hole.
                if any(recorded_path is None for recorded_path in recorded):
                    self._banned_paths[client_ip] = None
                else:
                    self._banned_paths[client_ip] = frozenset(
                        recorded_path
                        for recorded_path in recorded
                        if recorded_path is not None
                    )
                self._banned_until[client_ip] = now + self._ban_seconds
                del self._strikes[client_ip]
            self._trim(now)

    def is_banned(
        self, client_ip: str, path: str | None = None, *, now: float | None = None
    ) -> bool:
        """Whether `client_ip` is banned, optionally narrowed to `path`.

        `path=None` reports whether the client is banned at all, ignoring the
        scope; pass a path to ask the question the access gate actually asks.
        """
        if not self.enabled or not client_ip or _is_loopback(client_ip):
            return False
        now = now if now is not None else time.monotonic()
        with self._lock:
            until = self._banned_until.get(client_ip)
            if until is None:
                return False
            if until <= now:
                del self._banned_until[client_ip]
                self._banned_paths.pop(client_ip, None)
                return False
            if path is None:
                return True
            banned_paths = self._banned_paths.get(client_ip)
            return banned_paths is None or path in banned_paths

    def ban_remaining_seconds(self, client_ip: str, *, now: float | None = None) -> int:
        now = now if now is not None else time.monotonic()
        with self._lock:
            return max(0, int(self._banned_until.get(client_ip, 0) - now))

    def _trim(self, now: float) -> None:
        """Bound memory: expire stale strikes, then drop oldest entries over cap."""
        for ip in list(self._strikes):
            strikes = self._strikes[ip]
            while strikes and strikes[0][0] < now - self._window_seconds:
                strikes.popleft()
            if not strikes:
                del self._strikes[ip]
        while len(self._strikes) + len(self._banned_until) > self._max_tracked:
            oldest = next(iter(self._strikes), None)
            if oldest is None:
                break
            del self._strikes[oldest]


def _is_loopback(ip_str: str) -> bool:
    # Behind a trusted proxy (TRUST_PROXY) a loopback *key* can only come from
    # spoofable headers or the proxy hop itself, and dev self-ban protection
    # is unnecessary — exemptions apply only to direct-peer deployments.
    if settings.trust_proxy:
        return False
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
    loopback peers unless TRUST_PROXY is set (behind a proxy the peer is a
    local hop, not the client; direct loopback is dev traffic).

    The request path scopes the eventual ban, so an over-limit client is
    confined to the route that misbehaved.
    """
    from services.portfolio.rate_limiter import get_client_ip, peer_is_loopback

    if not settings.trust_proxy and peer_is_loopback(request):
        return
    violation_tracker.record(get_client_ip(request), request.url.path)
