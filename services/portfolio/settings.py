from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # See .env.example for detailed documentation of all environment variables.
    # env_file is the sole .env loader: every var in .env must be a declared
    # field here, or startup fails fast (extra="forbid") instead of silently
    # ignoring a typo'd setting.
    model_config = SettingsConfigDict(env_prefix="", env_file=".env")

    # Core
    environment: str = "development"
    cv_data_path: Path = Path("data/cv.json")
    port: int = 8080

    # OpenAPI / Swagger UI metadata
    contact_name: str = ""
    contact_email: str = ""

    # Base URL of the games service. Empty = same-origin (local dev, where the
    # games router is mounted in this app). In production the games workload is
    # a separate Cloud Run service on its own host, so set e.g.
    # "https://games.example.com" — no trailing slash.
    games_base_url: str = ""

    # CV content delivery (GCS)
    cv_data_gcs_uri: str = ""
    cv_refresh_seconds: int = 30

    # Rate limiting and access control
    trust_proxy: bool = False
    client_ip_xff_entry: int = 0
    client_ip_header: str = ""
    blocked_ips: str = ""
    allowed_ips: str = ""
    blocked_ips_file: Path | None = None
    allowed_ips_file: Path | None = None

    # Scheduled availability
    service_hours_start: str = ""
    service_hours_end: str = ""
    service_days: str = ""
    service_timezone: str = ""

    # Dynamic rate-limit bans (fail2ban-lite)
    failban_threshold: int = 0
    failban_window_seconds: int = 900
    failban_ban_seconds: int = 1800
    failban_max_tracked: int = 10000

    # JWT auth and user store (Phase 1c+)
    jwt_audience: str = "cv-rest-mcp-server"
    jwt_issuer: str = "https://api.example.com"
    cors_origin: str = "https://app.example.com"
    jwt_signing_key: str = ""
    refresh_token_pepper: str = ""
    # Postgres connection string, asyncpg driver (e.g.
    # "postgresql+asyncpg://user:pass@host:5432/dbname"). No default: the
    # app lifespan (main.py) and Alembic (db_migrations.py, alembic/env.py)
    # both fail fast if this is unset rather than silently running against
    # nothing.
    database_url: str = ""
    first_admin_username: str = "operator"
    first_admin_email: str = "operator@example.com"
    first_admin_password: str = ""
    first_admin_password_file: Path | None = None
    access_token_ttl_minutes: int = 10
    refresh_token_ttl_days: int = 30

    # Skill bank (CV tailor + MCP match_jd)
    cv_baseline_path: Path = Path("data/cv_baseline.json")
    jd_vocabulary_path: Path = Path("data/jd_vocabulary.json")
    cv_tailored_dir: Path = Path("data/tailored")

    @property
    def sync_database_url(self) -> str:
        """`database_url` with the async driver swapped for a sync one.

        Alembic runs migrations synchronously, so it (and anything else that
        needs a blocking connection, e.g. a throwaway per-test database setup)
        uses this instead of the asyncpg URL the running app connects with.
        Single place this swap happens — nothing else should string-replace
        `database_url` by hand.
        """
        return self.database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg://"
        )


settings = Settings()
