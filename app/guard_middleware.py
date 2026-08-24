from starlette.requests import Request
from starlette.responses import JSONResponse

from app import failban
from app.ip_lists import ip_in_networks, load_ip_list
from app.rate_limiter import get_client_ip
from app.service_hours import is_within_service_hours
from app.settings import settings


class GuardMiddleware:
    """Pure-ASGI access gate evaluated before all other middleware.

    Order: allowlist -> static blocklist -> dynamic ban -> service hours.
    /health always passes so monitoring stays independent of policy.
    When no policy is configured, requests pass through untouched.
    """

    def __init__(self, app) -> None:
        self.app = app
        self.allowed = load_ip_list(settings.allowed_ips, settings.allowed_ips_file)
        self.blocked = load_ip_list(settings.blocked_ips, settings.blocked_ips_file)
        self.hours_enabled = bool(
            settings.service_hours_start.strip() and settings.service_hours_end.strip()
        )
        self.any_policy_enabled = bool(
            self.allowed
            or self.blocked
            or self.hours_enabled
            or failban.violation_tracker.enabled
        )

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("path") == "/health"
            or not self.any_policy_enabled
        ):
            await self.app(scope, receive, send)
            return

        client_ip = get_client_ip(Request(scope))

        if self.allowed and not ip_in_networks(client_ip, self.allowed):
            await self._deny(
                scope, receive, send, 403, "Client IP is not in the allowed list"
            )
            return

        if ip_in_networks(client_ip, self.blocked):
            await self._deny(scope, receive, send, 403, "Client IP is blocked")
            return

        tracker = failban.violation_tracker
        if tracker.is_banned(client_ip):
            await self._deny(
                scope,
                receive,
                send,
                403,
                "Temporarily banned due to repeated rate-limit violations",
                retry_after=tracker.ban_remaining_seconds(client_ip),
            )
            return

        if not is_within_service_hours():
            await self._deny(
                scope,
                receive,
                send,
                503,
                "Service is outside its scheduled availability window",
            )
            return

        await self.app(scope, receive, send)

    async def _deny(
        self,
        scope,
        receive,
        send,
        status_code: int,
        detail: str,
        *,
        retry_after: int | None = None,
    ) -> None:
        headers = {}
        if retry_after:
            headers["Retry-After"] = str(retry_after)
        response = JSONResponse(
            {"detail": detail}, status_code=status_code, headers=headers or None
        )
        await response(scope, receive, send)
