import pytest

from services.portfolio import failban
from services.portfolio.failban import ViolationTracker
from services.portfolio.guard_middleware import GuardMiddleware
from services.portfolio.ip_lists import ip_in_networks, load_ip_list, parse_ip_list


# --- ip_lists ---


def test_parse_ip_list_single_ips_and_cidrs():
    nets = parse_ip_list("203.0.113.5, 10.0.0.0/8, 2001:db8::/32")
    assert len(nets) == 3


def test_parse_ip_list_accepts_newline_separated_entries():
    nets = parse_ip_list("203.0.113.5\n10.0.0.0/8\r\n2001:db8::/32")
    assert len(nets) == 3


def test_parse_ip_list_skips_comments_and_blank_lines():
    raw = "# header comment\n203.0.113.5\n\n  # indented comment\n10.0.0.0/8 # trailing"
    nets = parse_ip_list(raw)
    assert len(nets) == 2


def test_parse_ip_list_comment_may_contain_commas():
    raw = "# generated file, do not edit by hand.\n203.0.113.5"
    assert len(parse_ip_list(raw)) == 1


def test_parse_ip_list_treats_bare_ip_as_host_network():
    nets = parse_ip_list("203.0.113.5")
    assert ip_in_networks("203.0.113.5", nets)
    assert not ip_in_networks("203.0.113.6", nets)


def test_parse_ip_list_empty_string_is_no_networks():
    assert parse_ip_list("") == []
    assert parse_ip_list("  ") == []


def test_parse_ip_list_fails_fast_on_invalid_entry():
    with pytest.raises(ValueError, match="Invalid IP or CIDR"):
        parse_ip_list("10.0.0.1, not-an-ip")


def test_cidr_membership():
    nets = parse_ip_list("10.0.0.0/8")
    assert ip_in_networks("10.1.2.3", nets)
    assert not ip_in_networks("11.0.0.1", nets)


def test_membership_with_invalid_ip_string_is_false():
    assert not ip_in_networks("garbage", parse_ip_list("10.0.0.0/8"))


# --- ip list files ---


def test_load_ip_list_reads_file(tmp_path):
    list_file = tmp_path / "blocked.txt"
    list_file.write_text("# geo\n192.0.2.0/24\n", encoding="utf-8")
    nets = load_ip_list(list_file)
    assert len(nets) == 1
    assert ip_in_networks("192.0.2.9", nets)


def test_load_ip_list_without_file_is_empty():
    assert load_ip_list(None) == []


def test_load_ip_list_missing_file_fails_fast(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_ip_list(tmp_path / "nope.txt")


# --- fail2ban-lite tracker ---


def _tracker(**overrides):
    defaults = dict(
        threshold=3,
        window_seconds=900,
        ban_seconds=1800,
        max_tracked=100,
    )
    return ViolationTracker(**{**defaults, **overrides})


def test_tracker_disabled_when_threshold_zero():
    tracker = _tracker(threshold=0)
    for _ in range(10):
        tracker.record("198.51.100.1")
    assert not tracker.is_banned("198.51.100.1")


def test_tracker_bans_after_threshold_violations():
    tracker = _tracker()
    for _ in range(3):
        tracker.record("198.51.100.1")
    assert tracker.is_banned("198.51.100.1")
    assert 0 < tracker.ban_remaining_seconds("198.51.100.1") <= 1800


def test_tracker_strikes_expire_outside_window():
    tracker = _tracker(window_seconds=100)
    t = 1000.0
    tracker.record("198.51.100.1", now=t)
    tracker.record("198.51.100.1", now=t + 90)
    tracker.record("198.51.100.1", now=t + 200)  # first strike aged out
    assert not tracker.is_banned("198.51.100.1")


def test_tracker_ban_expires():
    tracker = _tracker(ban_seconds=50)
    t = 1000.0
    for _ in range(3):
        tracker.record("198.51.100.1", now=t)
    assert tracker.is_banned("198.51.100.1", now=t + 49)
    assert not tracker.is_banned("198.51.100.1", now=t + 51)


def test_tracker_never_bans_loopback():
    tracker = _tracker()
    for _ in range(10):
        tracker.record("127.0.0.1")
    assert not tracker.is_banned("127.0.0.1")


# --- path-scoped bans ---


def test_ban_confined_to_the_offending_path():
    tracker = _tracker()
    for _ in range(3):
        tracker.record("198.51.100.1", "/cv/pdf")
    assert tracker.is_banned("198.51.100.1", "/cv/pdf")
    assert not tracker.is_banned("198.51.100.1", "/cv")
    assert not tracker.is_banned("198.51.100.1", "/cv/html")


def test_ban_covers_every_path_that_tripped():
    tracker = _tracker()
    tracker.record("198.51.100.1", "/cv/pdf")
    tracker.record("198.51.100.1", "/cv/pdf")
    tracker.record("198.51.100.1", "/api/v1/cv/pdf")
    assert tracker.is_banned("198.51.100.1", "/cv/pdf")
    assert tracker.is_banned("198.51.100.1", "/api/v1/cv/pdf")
    assert not tracker.is_banned("198.51.100.1", "/cv")


def test_unattributed_violation_bans_every_path():
    """A strike with no resolvable path must not leave an enforcement hole."""
    tracker = _tracker()
    for _ in range(3):
        tracker.record("198.51.100.1")
    assert tracker.is_banned("198.51.100.1", "/cv/pdf")
    assert tracker.is_banned("198.51.100.1", "/cv")


def test_scoped_ban_expires_and_frees_every_path():
    tracker = _tracker(ban_seconds=50)
    t = 1000.0
    for _ in range(3):
        tracker.record("198.51.100.1", "/cv/pdf", now=t)
    assert tracker.is_banned("198.51.100.1", "/cv/pdf", now=t + 49)
    assert not tracker.is_banned("198.51.100.1", "/cv/pdf", now=t + 51)


def test_scoped_ban_is_not_reported_as_banned_on_a_clean_path():
    """`is_banned(ip)` without a path answers "banned at all", not per-path."""
    tracker = _tracker()
    for _ in range(3):
        tracker.record("198.51.100.1", "/cv/pdf")
    assert tracker.is_banned("198.51.100.1")
    assert not tracker.is_banned("198.51.100.2")


def test_tracker_prunes_to_max_tracked():
    tracker = _tracker(threshold=999, max_tracked=5)
    for i in range(20):
        tracker.record(f"198.51.100.{i}", now=1000.0 + i)
    assert len(tracker._strikes) <= 5


# --- register_violation_from_request (loopback gating vs TRUST_PROXY) ---


def _scope_request(ip="127.0.0.1", path="/"):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "headers": [],
            "path": path,
            "query_string": b"",
            "client": None if ip is None else (ip, 12345),
        }
    )


def test_register_skips_loopback_by_default(monkeypatch):
    tracker = _tracker(threshold=1)
    monkeypatch.setattr(failban, "violation_tracker", tracker)
    monkeypatch.setattr(failban.settings, "trust_proxy", False)
    failban.register_violation_from_request(_scope_request("127.0.0.1"))
    assert not tracker.is_banned("127.0.0.1")


def test_register_bans_loopback_when_trust_proxy(monkeypatch):
    tracker = _tracker(threshold=1)
    monkeypatch.setattr(failban, "violation_tracker", tracker)
    monkeypatch.setattr(failban.settings, "trust_proxy", True)
    failban.register_violation_from_request(_scope_request("127.0.0.1"))
    assert tracker.is_banned("127.0.0.1")


def test_register_scopes_violation_to_the_request_path(monkeypatch):
    tracker = _tracker(threshold=1)
    monkeypatch.setattr(failban, "violation_tracker", tracker)
    monkeypatch.setattr(failban.settings, "trust_proxy", True)
    failban.register_violation_from_request(_scope_request("198.51.100.5", "/cv/pdf"))
    assert tracker.is_banned("198.51.100.5", "/cv/pdf")
    assert not tracker.is_banned("198.51.100.5", "/cv")


# --- GuardMiddleware (direct ASGI scope calls) ---


def _scope(ip="198.51.100.7", path="/cv"):
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "client": (ip, 44444),
        "headers": [],
    }


async def _run_guard(guard, scope):
    sent = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        sent.append({"type": "passthrough"})

    guard.app = downstream
    await guard(scope, receive, send)
    return sent


def _guard_with(monkeypatch, *, tracker=None, **settings_overrides):
    from services.portfolio.settings import settings

    defaults = {
        "allowed_ips_file": None,
        "blocked_ips_file": None,
    }
    for key, value in {**defaults, **settings_overrides}.items():
        monkeypatch.setattr(settings, key, value)
    if tracker is not None:
        monkeypatch.setattr(failban, "violation_tracker", tracker)
    return GuardMiddleware(app=None)


def _ip_list_file(tmp_path, name: str, contents: str):
    list_file = tmp_path / name
    list_file.write_text(contents, encoding="utf-8")
    return list_file


async def test_guard_passthrough_when_no_policies(monkeypatch):
    guard = _guard_with(monkeypatch)
    sent = await _run_guard(guard, _scope())
    assert {"type": "passthrough"} in sent


async def test_guard_health_always_passes_even_blocked(monkeypatch, tmp_path):
    blocked_file = _ip_list_file(tmp_path, "blocked.txt", "0.0.0.0/0\n")
    guard = _guard_with(monkeypatch, blocked_ips_file=blocked_file)
    sent = await _run_guard(guard, _scope(path="/health"))
    assert {"type": "passthrough"} in sent


async def test_guard_blocklist_denies(monkeypatch, tmp_path):
    blocked_file = _ip_list_file(tmp_path, "blocked.txt", "198.51.100.0/24\n")
    guard = _guard_with(monkeypatch, blocked_ips_file=blocked_file)
    sent = await _run_guard(guard, _scope(ip="198.51.100.7"))
    status = next(m for m in sent if m["type"] == "http.response.start")
    assert status["status"] == 403


async def test_guard_blocked_ips_file_denies(monkeypatch, tmp_path):
    list_file = _ip_list_file(tmp_path, "geo.txt", "# generated\n198.51.100.0/24\n")
    guard = _guard_with(monkeypatch, blocked_ips_file=list_file)
    sent = await _run_guard(guard, _scope(ip="198.51.100.7"))
    status = next(m for m in sent if m["type"] == "http.response.start")
    assert status["status"] == 403


async def test_guard_allowlist_blocks_unlisted_clients(monkeypatch, tmp_path):
    allowed_file = _ip_list_file(tmp_path, "allowed.txt", "203.0.113.0/24\n")
    guard = _guard_with(monkeypatch, allowed_ips_file=allowed_file)
    denied = await _run_guard(guard, _scope(ip="198.51.100.7"))
    allowed = await _run_guard(guard, _scope(ip="203.0.113.9"))
    assert (
        next(m for m in denied if m["type"] == "http.response.start")["status"] == 403
    )
    assert {"type": "passthrough"} in allowed


async def test_guard_dynamic_ban_denies_with_retry_after(monkeypatch):
    tracker = _tracker(threshold=1)
    tracker.record("198.51.100.7")
    guard = _guard_with(monkeypatch, tracker=tracker)
    sent = await _run_guard(guard, _scope(ip="198.51.100.7"))
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 403
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    assert int(headers["retry-after"]) > 0


async def test_guard_scoped_ban_only_denies_the_offending_path(monkeypatch):
    """A client banned on one route keeps full access to the rest of the site."""
    tracker = _tracker(threshold=1)
    tracker.record("198.51.100.7", "/cv/pdf")
    guard = _guard_with(monkeypatch, tracker=tracker)
    denied = await _run_guard(guard, _scope(ip="198.51.100.7", path="/cv/pdf"))
    still_allowed = await _run_guard(guard, _scope(ip="198.51.100.7", path="/cv"))
    assert (
        next(m for m in denied if m["type"] == "http.response.start")["status"] == 403
    )
    assert {"type": "passthrough"} in still_allowed


# --- end-to-end: a real 429 storm must not lock a recruiter out of the CV ---


async def test_pdf_rate_limit_ban_still_serves_the_html_cv(
    monkeypatch, override_pdf_service
):
    """The recruiter-facing guarantee, through the real app.

    A ban earned on /cv/pdf must remain scoped to that route, leaving the
    public CV pages the service exists to serve untouched.
    """
    from httpx import ASGITransport, AsyncClient

    from services.portfolio.main import app
    from services.portfolio.rate_limiter import limiter
    from services.portfolio.settings import settings

    monkeypatch.setattr(settings, "trust_proxy", True)
    monkeypatch.setattr(settings, "client_ip_xff_entry", 2)

    tracker = _tracker(threshold=1)  # a single strike earns the ban
    monkeypatch.setattr(failban, "violation_tracker", tracker)

    for middleware in app.user_middleware:
        if isinstance(middleware, GuardMiddleware):
            middleware.any_policy_enabled = True

    limiter.reset()
    client_ip = "198.51.100.42"
    xff = {"X-Forwarded-For": f"{client_ip}, 10.0.0.1"}

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=xff
        ) as ac:
            # The 5/15minute limit passes 5; drive 6+ so we get 429 strikes.
            for _ in range(6):
                await ac.get("/cv/pdf?theme=classic")
            # The ban is recorded and scoped to /cv/pdf only — the invariant
            # the guard enforces (403 here; which middleware answers first on
            # an already-throttled route depends on stack order, so don't
            # assert the exact status).
            assert tracker.is_banned(client_ip, "/cv/pdf")
            assert not tracker.is_banned(client_ip, "/cv")
            assert not tracker.is_banned(client_ip, "/cv/html")

            # End-to-end: /cv/pdf is refused (429 or 403), and — critically —
            # the routes the client never overran keep serving, so a
            # recruiter who trips the PDF limit still gets the CV.
            assert (await ac.get("/cv/pdf?theme=classic")).status_code in {403, 429}
            assert (await ac.get("/cv?theme=classic")).status_code == 200
            assert (await ac.get("/cv/html?theme=classic")).status_code == 200
    finally:
        limiter.reset()
