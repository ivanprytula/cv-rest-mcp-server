from datetime import UTC, datetime
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from services.portfolio.settings import settings


_WEEKDAYS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def parse_service_days(raw: str) -> set[int] | None:
    """Parse comma-separated weekday names into weekday numbers.
    None means every day. Fails fast on unknown names."""
    raw = raw.strip()
    if not raw:
        return None
    days: set[int] = set()
    for part in raw.split(","):
        key = part.strip().lower()[:3]
        if key not in _WEEKDAYS:
            raise ValueError(
                f"Invalid weekday in SERVICE_DAYS: {part!r} (expected e.g. mon,wed,fri)"
            )
        days.add(_WEEKDAYS[key])
    return days


def service_now(now_utc: datetime | None = None) -> datetime:
    now_utc = now_utc or datetime.now(UTC)
    tz_name = settings.service_timezone
    if not tz_name:
        return now_utc
    return now_utc.astimezone(ZoneInfo(tz_name))


def is_within_service_hours(now: datetime | None = None) -> bool:
    """Whether the service is inside its configured availability window.

    Empty start/end means always open. Overnight windows (start > end) are
    supported. service_days restricts weekdays; it only applies when hours
    are configured.
    """
    start_raw = settings.service_hours_start.strip()
    end_raw = settings.service_hours_end.strip()
    if not start_raw or not end_raw:
        return True

    local = service_now(now)
    allowed_days = parse_service_days(settings.service_days)
    if allowed_days is not None and local.weekday() not in allowed_days:
        return False

    start = _parse_hhmm(start_raw)
    end = _parse_hhmm(end_raw)
    current = local.time().replace(tzinfo=None)
    if start <= end:
        return start <= current <= end
    # Overnight window (e.g. 22:00-06:00)
    return current >= start or current <= end


def _parse_hhmm(raw: str) -> dt_time:
    hours, minutes = raw.split(":")
    hour, minute = int(hours), int(minutes)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time of day: {raw!r} (expected HH:MM)")
    return dt_time(hour, minute)
