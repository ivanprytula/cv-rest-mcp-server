"""Runs Alembic migrations programmatically (Phase 2, ADR-023).

Replaces the old `Base.metadata.create_all` lifespan call — schema is now
migration-managed, not derived ad-hoc from the current model state. Shared by
the app lifespan (main.py) and the test suite's Postgres fixture, which both
need to bring a fresh or existing database up to `head` before use.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config


_ALEMBIC_INI = Path(__file__).resolve().parent / "alembic.ini"


async def upgrade_head(sync_db_url: str) -> None:
    """Run `alembic upgrade head` against `sync_db_url` (a sync-driver URL —
    see `settings.sync_database_url`, never the app's asyncpg URL directly).

    Alembic itself runs synchronously, so this offloads to a thread rather
    than blocking the event loop (called from an async lifespan/fixture).
    """

    def _run() -> None:
        config = Config(str(_ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", sync_db_url)
        command.upgrade(config, "head")

    await asyncio.to_thread(_run)
