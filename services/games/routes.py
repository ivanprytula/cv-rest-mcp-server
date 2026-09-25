"""Extracted bingo routes for the games service (Phase 1b split)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Query, Request
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
PAGE_SIZE = 20


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


def _render_bingo_template(title: str, total_cards: int, total_pages: int) -> str:
    template = _jinja_env.get_template("games/culture_bingo.html")
    return template.render(
        title=title,
        total_cards=total_cards,
        total_pages=total_pages,
        page_size=PAGE_SIZE,
        portfolio_base_url=settings.portfolio_base_url.rstrip("/"),
    )


def _interleave_cells(cells: list[dict]) -> list[dict]:
    """Interleave green/red/yellow cards so every batch has a mix."""
    buckets = [
        [c for c in cells if c["id"].startswith(f"{color}-")]
        for color in ("green", "red", "yellow")
    ]
    depth = max((len(bucket) for bucket in buckets), default=0)
    return [bucket[i] for i in range(depth) for bucket in buckets if i < len(bucket)]


_BINGO_CONTENT = load_bingo_content(GAMES_CONTENT_PATH)
_BINGO_CELLS_MIXED = _interleave_cells(_BINGO_CONTENT["cells"])

router = APIRouter()


@router.get("/culture-bingo", tags=["Games"])
async def culture_bingo(request: Request):
    """Company Culture Bingo: paged interactive browser game with click-to-reveal tiles."""
    total_pages = max(1, -(-len(_BINGO_CELLS_MIXED) // PAGE_SIZE))  # ceiling division
    html = _render_bingo_template(
        title=_BINGO_CONTENT.get("title", "Company Culture Bingo"),
        total_cards=len(_BINGO_CELLS_MIXED),
        total_pages=total_pages,
    )
    return HTMLResponse(content=html)


@router.get("/api/v1/culture-bingo/cards", tags=["Games"])
@limits("60/minute", "300/hour")
async def bingo_cards(
    request: Request,
    page: int = Query(0, ge=0, description="Zero-based page index"),
):
    """Return one page of bingo cards (interleaved green/red/yellow, PAGE_SIZE cards per page).

    Clients track progress in localStorage and call this endpoint to fetch
    the next batch. Fixed order means page indices are stable across sessions.
    """
    total = len(_BINGO_CELLS_MIXED)
    total_pages = max(1, -(-total // PAGE_SIZE))
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    return {
        "page": page,
        "total_pages": total_pages,
        "total_cards": total,
        "page_size": PAGE_SIZE,
        "cells": _BINGO_CELLS_MIXED[start:end],
    }
