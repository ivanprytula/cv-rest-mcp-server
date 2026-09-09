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

    # Base URL of the games service. Empty = same-origin (local dev, where the
    # games router is mounted in this app). In production the games workload is
    # a separate Cloud Run service on its own host, so set e.g.
    # "https://games.example.com" — no trailing slash.
    games_base_url: str = ""

    # Unused by this service — declared only because .env is shared with
    # services/games (its "back to portfolio" link, services/games/settings.py).
    # extra="forbid" below rejects any undeclared var, so every service sharing
    # this .env must declare the other services' vars too, even unused here.
    portfolio_base_url: str = ""

    # CV content delivery (GCS)
    cv_data_gcs_uri: str = ""
    cv_refresh_seconds: int = 30

    # Rate limiting and access control
    trust_proxy: bool = False
    client_ip_xff_entry: int = 0
    blocked_ips_file: Path | None = None
    allowed_ips_file: Path | None = None

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
    # app lifespan and Alembic both fail fast if this is unset rather than
    # silently running against nothing.
    #
    # Connect as the application role, never a superuser: row-level security
    # does not apply to one, so the tenant policy would be inert. Startup
    # refuses such a role outright (`verify_rls_enforced`).
    database_url: str = ""
    first_admin_username: str = "operator"
    first_admin_email: str = "operator@example.com"
    first_admin_password: str = ""
    first_admin_password_file: Path | None = None
    access_token_ttl_minutes: int = 10
    refresh_token_ttl_days: int = 30

    # Skill bank (CV tailor + MCP match_job_posting)
    cv_baseline_path: Path = Path("data/cv_baseline.json")
    jd_vocabulary_path: Path = Path("data/jd_vocabulary.json")
    cv_tailored_dir: Path = Path("data/tailored")

    # Job-posting document store (Phase 2b PR8). Empty = no Firestore project
    # configured — local dev runs on an in-memory fake instead, same "empty
    # means skip" pattern as cv_data_gcs_uri above. Set to the GCP project id
    # to use the real Firestore-backed store.
    firestore_project: str = ""

    # Migrations connect as a more privileged role: they issue DDL, which the
    # app deliberately cannot. Two URLs rather than one connection that
    # switches role on the fly, because `SET ROLE` is reversible — a superuser
    # session that drops to the app role can `RESET ROLE` back, so a bug or an
    # injection undoes the isolation. A genuine app-role connection is refused
    # the escalation by Postgres ("permission denied to set role"), which is
    # what makes the boundary real.
    #
    # Empty means "same credentials as database_url", for a deployment whose
    # app role may legitimately migrate.
    migration_database_url: str = ""

    @property
    def sync_database_url(self) -> str:
        """The migration URL, with a sync driver.

        Alembic runs synchronously, so it (and anything else needing a
        blocking connection, e.g. a throwaway per-test database) uses this
        rather than the app's asyncpg URL. Single place the swap happens —
        nothing else should string-replace a URL by hand.

        Falls back to `database_url` when no migration URL is configured, so
        an install where one role does both keeps working unchanged.
        """
        url = self.migration_database_url or self.database_url
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


settings = Settings()
