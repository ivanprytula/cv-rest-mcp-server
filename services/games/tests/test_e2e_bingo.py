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


@pytest.fixture
def mobile_page(browser, live_server):
    """A 375x667 touch context — the narrowest layout the game targets."""
    context = browser.new_context(
        base_url=live_server, viewport={"width": 375, "height": 667}, has_touch=True
    )
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


def test_no_horizontal_overflow_on_a_phone(mobile_page):
    page = mobile_page
    page.goto("/culture-bingo")
    page.wait_for_selector(".cell[data-id]")

    widths = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert widths <= 0, f"page scrolls sideways by {widths}px"


def test_grid_tracks_stay_equal_and_inside_the_board(mobile_page):
    """A bare 1fr track is minmax(auto, 1fr): a long tile word floors its
    track at min-content, the tracks stop being equal, and the board's
    overflow:hidden silently clips the last column. minmax(0, 1fr) is the fix
    and this is what keeps it in place."""
    page = mobile_page
    page.goto("/culture-bingo")
    page.wait_for_selector(".cell[data-id]")

    result = page.evaluate(
        """() => {
            const grid = document.getElementById('grid');
            const box = grid.getBoundingClientRect();
            const cells = [...grid.querySelectorAll('.cell[data-id]')].map(c => {
                const r = c.getBoundingClientRect();
                return {w: Math.round(r.width), spills: r.right > box.right + 0.5};
            });
            return {
                widths: [...new Set(cells.map(c => c.w))],
                spilling: cells.filter(c => c.spills).length,
            };
        }"""
    )

    assert len(result["widths"]) == 1, f"unequal columns: {result['widths']}"
    assert result["spilling"] == 0, f"{result['spilling']} tiles clipped by the board"


def test_touch_targets_are_at_least_44px(mobile_page):
    """The controls are finger-operated; a 35px reset button is a mis-tap."""
    page = mobile_page
    page.goto("/culture-bingo")
    page.wait_for_selector(".cell[data-id]")

    too_small = page.evaluate(
        """() => [...document.querySelectorAll('button, a')]
            .map(e => ({e, r: e.getBoundingClientRect()}))
            .filter(x => x.r.width && (x.r.height < 44 || x.r.width < 44))
            .map(x => `${x.e.tagName.toLowerCase()}${x.e.id ? '#' + x.e.id : ''} `
                      + `${Math.round(x.r.width)}x${Math.round(x.r.height)}`)"""
    )
    assert not too_small, f"undersized touch targets: {too_small}"


def test_title_stays_clear_of_the_theme_toggle(mobile_page):
    """The theme toggle is position:fixed in the top-right corner and the title
    is centred, so the header reserves that corner with a symmetric gutter.
    Asserted on the title's *box*, not its ink: the current title leaves only
    ~13px of slack in the reserved space, and ink-only checking would pass for
    any heading until the day someone lengthens it.
    """
    page = mobile_page
    page.goto("/culture-bingo")

    box = page.evaluate(
        """() => {
            const h1 = document.querySelector('h1');
            const t = document.querySelector('#theme-toggle');
            const a = h1.getBoundingClientRect(), b = t.getBoundingClientRect();
            const intersects = !(a.right <= b.left || a.left >= b.right
                              || a.bottom <= b.top || a.top >= b.bottom);
            return {intersects, h1mid: (a.left + a.right) / 2, vw: window.innerWidth};
        }"""
    )
    assert not box["intersects"], "title box collides with the fixed theme toggle"
    assert abs(box["h1mid"] - box["vw"] / 2) < 1, "title is not centred"


def test_completion_overlay_is_pinned_to_the_viewport(mobile_page):
    """The board is taller than a phone screen, so an overlay anchored to the
    grid's centre ends up off-screen once the player scrolls down to tap the
    last tile. It is pinned to the viewport instead.

    Asserts the overlay's own box spans the viewport — a property of
    position:fixed, independent of how tall the board happens to be. Merely
    checking the buttons are on-screen would pass for a board short enough
    that the board's centre is still visible, which is the regression's
    lucky case, not its fixed one.
    """
    page = mobile_page
    page.goto("/culture-bingo")
    cells = page.locator(".cell[data-id]")
    for i in range(cells.count()):
        cells.nth(i).click()
    expect(page.locator("#overlay")).to_have_class(re.compile(r"show"))
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    box = page.evaluate(
        """() => {
            const r = document.querySelector('#overlay').getBoundingClientRect();
            return {top: r.top, left: r.left,
                    height: r.height, width: r.width,
                    vh: window.innerHeight, vw: window.innerWidth};
        }"""
    )
    assert abs(box["top"]) < 1 and abs(box["left"]) < 1, (
        f"overlay not at the viewport origin: {box}"
    )
    assert abs(box["height"] - box["vh"]) < 1, (
        f"overlay does not span the viewport: {box}"
    )
    assert abs(box["width"] - box["vw"]) < 1, (
        f"overlay does not span the viewport: {box}"
    )

    expect(page.locator("#btn-continue")).to_be_in_viewport()
    expect(page.locator("#btn-replay")).to_be_in_viewport()
