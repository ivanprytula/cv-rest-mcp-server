"""End-to-end Culture Bingo flows driven by a real browser (Playwright).

Covers the JS behaviors invisible to httpx-level tests in test_bingo.py:
one-click reveal (diagonal split fill), re-click and right-click being no-ops,
progress tracking, the completion overlay, and reset.

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
from services.games.routes import PAGE_SIZE


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


BATCH_SIZE = PAGE_SIZE


def test_bingo_page_loads_with_grid(page):
    page.goto("/culture-bingo")
    expect(page.locator("h1")).to_have_text("Company Culture Bingo")
    cells = page.locator(".cell[data-id]")
    expect(cells.first).to_be_visible()
    assert cells.count() == BATCH_SIZE
    expect(page.locator("#progress")).to_have_text(f"0 / {BATCH_SIZE} revealed")
    expect(page.locator("#page-indicator")).to_have_text(re.compile(r"Batch 1 of \d+"))


def test_one_click_reveals_the_tile(page):
    page.goto("/culture-bingo")
    cell = page.locator(".cell[data-id]").first

    cell.click()

    expect(cell).to_have_class(re.compile(r"selected-(green|red|yellow)"))
    expect(page.locator("#progress")).to_have_text(f"1 / {BATCH_SIZE} revealed")
    # The split fill is a gradient layer, not a flat background colour.
    assert "gradient" in cell.evaluate("e => getComputedStyle(e).backgroundImage")


def test_revealing_a_tile_twice_keeps_it_revealed(page):
    """One click per tile is the whole interaction: a re-click must not toggle back."""
    page.goto("/culture-bingo")
    cell = page.locator(".cell[data-id]").first

    cell.click()
    cell.click()

    expect(cell).to_have_class(re.compile(r"selected-(green|red|yellow)"))
    expect(page.locator("#progress")).to_have_text(f"1 / {BATCH_SIZE} revealed")


def test_right_click_does_not_revert_a_revealed_tile(page):
    page.goto("/culture-bingo")
    cell = page.locator(".cell[data-id]").first

    cell.click()
    expect(cell).to_have_class(re.compile(r"selected-(green|red|yellow)"))

    cell.click(button="right")
    cell.dispatch_event("contextmenu")

    expect(cell).to_have_class(re.compile(r"selected-(green|red|yellow)"))
    expect(page.locator("#progress")).to_have_text(f"1 / {BATCH_SIZE} revealed")


def test_revealed_tile_has_no_marker_dot(page):
    """The dismissed-state colour dot is gone; the split fill is the whole signal."""
    page.goto("/culture-bingo")
    cell = page.locator(".cell[data-id]").first

    assert cell.evaluate("e => getComputedStyle(e, '::after').content") == "none"
    cell.click()
    assert cell.evaluate("e => getComputedStyle(e, '::after').content") == "none"


def test_reset_clears_the_current_batch(page):
    page.goto("/culture-bingo")
    cells = page.locator(".cell[data-id]")

    cells.nth(0).click()
    cells.nth(1).click()
    expect(page.locator("#progress")).to_have_text(f"2 / {BATCH_SIZE} revealed")

    page.click("#btn-reset")

    expect(page.locator("#progress")).to_have_text(f"0 / {BATCH_SIZE} revealed")
    for i in (0, 1):
        expect(cells.nth(i)).not_to_have_class(re.compile(r"selected-"))
    expect(page.locator("#overlay")).not_to_have_class(re.compile(r"show"))


def test_completing_all_tiles_shows_the_overlay(page):
    page.goto("/culture-bingo")
    cells = page.locator(".cell[data-id]")
    count = cells.count()

    # One click per tile reveals the whole batch.
    for i in range(count):
        cells.nth(i).click()

    expect(page.locator("#progress")).to_have_text(f"{count} / {count} revealed")
    expect(page.locator("#overlay")).to_have_class(re.compile(r"show"))
    expect(page.locator("#overlay-heading")).to_have_text("Batch 1 done")
    expect(page.locator("#btn-continue")).to_be_visible()


def test_cell_order_is_stable_across_reloads(page):
    """Batches are paged server-side in a fixed interleaved order (page indices
    are stable across sessions), so a reload must not reshuffle the batch."""
    page.goto("/culture-bingo")
    order1 = page.locator(".cell[data-id]").evaluate_all(
        "els => els.map(e => e.dataset.id)"
    )

    page.goto("/culture-bingo")
    order2 = page.locator(".cell[data-id]").evaluate_all(
        "els => els.map(e => e.dataset.id)"
    )

    assert order1 == order2
    assert len(order1) == BATCH_SIZE


def test_back_link_present_and_relative_without_portfolio_base_url(page):
    """PORTFOLIO_BASE_URL is unset in the test environment, so the template's
    empty-string fallback renders a same-origin link (see
    services/games/settings.py)."""
    page.goto("/culture-bingo")
    back_link = page.locator(".back-link")
    expect(back_link).to_have_text("← Back to portfolio")
    assert back_link.get_attribute("href") == "/"
