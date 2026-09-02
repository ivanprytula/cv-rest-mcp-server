"""Settings required by shared modules (rate_limiter, future shared infra).

Each service populates these from its own environment before shared modules are
imported.  No service should import services.portfolio.settings into shared/ — that creates
a hard coupling to the api-core dependency tree (GCS, WeasyPrint, MCP, etc.)
which games does not have.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class SharedSettings(BaseSettings):
    """Settings used by shared modules. Each service sets these in its env."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        extra="ignore",
    )

    # ── Client IP resolution (used by shared/rate_limiter.py) ────────────────
    trust_proxy: bool = False
    client_ip_xff_entry: int = 0
    client_ip_header: str = ""


# Module-level singleton — imported by shared/rate_limiter.py
shared_settings = SharedSettings()
