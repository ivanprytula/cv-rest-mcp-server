"""End-to-end UI flows driven by a real browser (Playwright).

Covers the JS behaviors invisible to httpx-level tests:
copy-to-clipboard, dark-mode toggle persistence, and the recruiter
consent click-through into the preview iframe.

Run with: just test-ui   (requires `uv run playwright install chromium`)
"""

import re
import socket
import threading
import time
import urllib.request

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from app.main import app


pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    """Real uvicorn server on a random loopback port for browser access."""
    config = uvicorn.Config(
        app, host="127.0.0.1", port=_free_port(), log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{config.port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base_url}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError("Live server failed to start")
    yield base_url
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        instance = p.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser, live_server):
    context = browser.new_context(base_url=live_server)
    page = context.new_page()
    yield page
    context.close()


def test_copy_button_writes_mcp_config_to_clipboard(browser, live_server):
    # Clipboard API needs explicit permission grants in headless Chromium.
    context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
    page = context.new_page()
    page.goto(f"{live_server}/")

    target = "config-claude-code"
    expected = page.locator(f"#{target}").inner_text()
    page.click(f"[data-copy-target='{target}']")

    expect(page.locator(f"[data-copy-target='{target}']")).to_have_text("Copied!")
    assert page.evaluate("navigator.clipboard.readText()") == expected

    # Button label reverts after the cooldown.
    expect(page.locator(f"[data-copy-target='{target}']")).to_have_text(
        "Copy", timeout=3000
    )
    context.close()


def test_config_tabs_switch_panels(page):
    page.goto("/")
    expect(page.locator("#config-claude-code")).to_be_visible()
    expect(page.locator("#config-codex")).to_be_hidden()

    page.click("[data-tab='codex']")
    expect(page.locator("#config-codex")).to_be_visible()
    expect(page.locator("#config-claude-code")).to_be_hidden()
    assert (
        "mcp_servers.cv-rest-mcp-server" in page.locator("#config-codex").inner_text()
    )
    assert (
        page.get_by_role("tab", name="Codex CLI").get_attribute("aria-selected")
        == "true"
    )


def test_dark_mode_toggle_persists_across_reload(page):
    page.goto("/")

    # Context defaults to light scheme; bootstrap must not enable dark yet.
    assert "dark" not in (page.locator("html").get_attribute("class") or "")

    page.click("#theme-toggle")
    expect(page.locator("html")).to_have_class("dark")
    assert page.evaluate("localStorage.getItem('theme')") == "dark"

    page.reload()
    assert "dark" in (page.locator("html").get_attribute("class") or "")


def test_recruiter_consent_flow_reaches_preview_iframe(page):
    page.goto("/")
    page.fill('input[name="company"]', "Acme Corp")
    page.check('input[name="consent"]')
    page.click('button[formaction="/cv/preview"]')

    expect(page).to_have_url(re.compile(r".*/cv/preview\?.*company=Acme"))
    assert "consent=1" in page.url

    frame = page.frame_locator("iframe")
    consent = frame.locator(".consent")
    expect(consent).to_be_visible()
    expect(consent).to_contain_text("art. 6 ust. 1 lit. a RODO")
    expect(consent).to_contain_text("Acme Corp")

    # Download button carries the same params forward.
    assert "consent=1" in page.locator('a:has-text("Download PDF")').get_attribute(
        "href"
    )


def test_landing_without_consent_shows_clean_cv(page):
    page.goto("/")
    page.click('button[formaction="/cv/preview"]')

    frame = page.frame_locator("iframe")
    expect(frame.locator(".consent")).to_have_count(0)
