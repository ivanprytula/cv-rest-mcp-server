"""End-to-end Culture Bingo flows driven by a real browser (Playwright).

Covers the JS behaviors invisible to httpx-level tests in test_bingo.py:
click-to-reveal, right-click-to-revert, progress tracking, the completion
overlay, and reset.

Run with: uv run pytest -m e2e --no-cov   (requires `playwright install chromium`)
"""

import re
import socket
import threading
import time
import urllib.request

import pytest
from playwright.sync_api import expect, sync_playwright

from services.games.main import app


pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    """Real uvicorn server on a random loopback port for browser access."""
    import uvicorn

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
    pg = context.new_page()
    yield pg
    context.close()


def test_bingo_page_loads_with_grid(page):
    page.goto("/culture-bingo")
    expect(page.locator("h1")).to_have_text("Company Culture Bingo")
    cells = page.locator(".cell")
    expect(cells.first).to_be_visible()
    assert cells.count() > 0
    expect(page.locator("#progress")).to_have_text("0 / 64 revealed")


def test_click_cell_selects_then_removes_on_second_click(page):
    page.goto("/culture-bingo")
    cell = page.locator(".cell").first

    # First click: reveal (colored, still present in the DOM/visible).
    cell.click()
    expect(cell).to_have_class(re.compile(r"selected-(green|red|yellow)"))
    expect(cell).not_to_have_class(re.compile(r"removed"))

    # Second click: remove (fades out, progress increments).
    cell.click()
    expect(cell).to_have_class(re.compile(r"removed"))
    expect(page.locator("#progress")).to_have_text("1 / 64 revealed")


def test_right_click_reverts_a_selected_cell(page):
    page.goto("/culture-bingo")
    cell = page.locator(".cell").first

    cell.click()
    expect(cell).to_have_class(re.compile(r"selected-(green|red|yellow)"))

    # Right-click before a second left-click reverts the selection, not a
    # browser context menu (JS calls preventDefault on contextmenu).
    cell.click(button="right")
    expect(cell).not_to_have_class(re.compile(r"selected-(green|red|yellow)"))
    expect(page.locator("#progress")).to_have_text("0 / 64 revealed")


def test_right_click_does_not_revert_a_removed_cell(page):
    page.goto("/culture-bingo")
    cell = page.locator(".cell").first

    cell.click()
    cell.click()  # now removed
    expect(cell).to_have_class(re.compile(r"removed"))

    # A removed cell sets pointer-events: none, so a real mouse right-click
    # cannot land on it (it would hit whatever is underneath instead) — that
    # is the correct, desired behavior for a faded-out cell. Dispatch the
    # contextmenu event directly to exercise the JS guard itself
    # (`if (state.removed.has(id)) return;` in revertCell), the same way a
    # keyboard or assistive-tech trigger would reach the handler.
    cell.dispatch_event("contextmenu")
    expect(cell).to_have_class(re.compile(r"removed"))
    expect(page.locator("#progress")).to_have_text("1 / 64 revealed")


def test_reset_clears_all_progress(page):
    page.goto("/culture-bingo")
    cells = page.locator(".cell")

    cells.nth(0).click()
    cells.nth(0).click()  # removed
    cells.nth(1).click()  # selected only
    expect(page.locator("#progress")).to_have_text("1 / 64 revealed")

    page.click("#reset")

    expect(page.locator("#progress")).to_have_text("0 / 64 revealed")
    expect(cells.nth(0)).not_to_have_class(re.compile(r"removed"))
    expect(cells.nth(1)).not_to_have_class(re.compile(r"selected-(green|red|yellow)"))
    expect(page.locator("#complete")).not_to_have_class("show")


def test_completing_all_cells_shows_the_overlay(page):
    page.goto("/culture-bingo")
    cells = page.locator(".cell")
    count = cells.count()

    # Two clicks per cell removes every one of them.
    for i in range(count):
        cell = cells.nth(i)
        cell.click()
        cell.click()

    expect(page.locator("#progress")).to_have_text(f"{count} / {count} revealed")
    expect(page.locator("#complete")).to_have_class(re.compile(r"show"))


def test_cell_order_differs_across_reloads(page):
    """Cells are shuffled server-side on every request (see test_bingo.py's
    httpx-level equivalent) — confirm the browser actually sees a new order,
    not a cached response."""
    page.goto("/culture-bingo")
    order1 = page.locator(".cell").evaluate_all("els => els.map(e => e.dataset.id)")

    page.goto("/culture-bingo")
    order2 = page.locator(".cell").evaluate_all("els => els.map(e => e.dataset.id)")

    assert order1 != order2


def test_back_link_present_and_relative_without_portfolio_base_url(page):
    """PORTFOLIO_BASE_URL is unset in the test environment, so the template's
    empty-string fallback renders a same-origin link (see
    services/games/settings.py)."""
    page.goto("/culture-bingo")
    back_link = page.locator(".back-link")
    expect(back_link).to_have_text("← Back to portfolio")
    assert back_link.get_attribute("href") == "/"
