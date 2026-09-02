"""Extracted bingo routes for the games service (Phase 1b split)."""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

from services.games.settings import settings
from shared.rate_limiter import limits


logger = logging.getLogger(__name__)

# Self-contained template loading — no app.* imports
TEMPLATE_DIR = Path(__file__).parent / "templates"
_loader = FileSystemLoader(str(TEMPLATE_DIR))
_jinja_env = Environment(loader=_loader, autoescape=True)

GAMES_CONTENT_PATH = Path(__file__).parent / "config" / "bingo_content.json"

_BINGO_REQUIRED_KEYS = {"id", "content"}


def load_bingo_content(path: Path) -> dict:
    """Parse and validate the bingo game content.

    A broken file aborts startup instead of silently serving an empty game.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Bingo content missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Bingo content is not valid JSON ({path}): {exc}") from exc

    if not isinstance(data, dict) or "cells" not in data:
        raise RuntimeError(f"{path}: expected object with 'cells' key")
    if not isinstance(data["cells"], list) or not data["cells"]:
        raise RuntimeError(f"{path}: 'cells' must be a non-empty list")

    for cell in data["cells"]:
        missing = _BINGO_REQUIRED_KEYS - cell.keys()
        if missing:
            raise RuntimeError(
                f"{path}: cell {cell.get('id', '?')!r} missing keys {sorted(missing)}"
            )
    return data


def _render_bingo_template(title: str, cells: list) -> str:
    template = _jinja_env.get_template("games/culture_bingo.html")
    return template.render(
        title=title,
        cells=cells,
        portfolio_base_url=settings.portfolio_base_url.rstrip("/"),
    )


_BINGO_CONTENT = load_bingo_content(GAMES_CONTENT_PATH)

router = APIRouter()


@router.get("/culture-bingo", tags=["Games"])
async def culture_bingo(request: Request):
    """Company Culture Bingo: interactive browser game with click-to-reveal tiles."""
    cells = list(_BINGO_CONTENT["cells"])
    random.shuffle(cells)
    html = _render_bingo_template(
        title=_BINGO_CONTENT.get("title", "Company Culture Bingo"),
        cells=cells,
    )
    return HTMLResponse(content=html)


@router.get("/api/games/culture-bingo/content", tags=["Games"])
@limits("30/minute", "120/hour")
async def bingo_content(request: Request):
    """Return the bingo game content as JSON."""
    return _BINGO_CONTENT
