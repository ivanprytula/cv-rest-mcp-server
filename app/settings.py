from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    cv_data_path: Path = Path("data/cv.json")
    port: int = 8080

    # OpenAPI / Swagger UI metadata shown in /docs. Empty = field omitted.
    # Kept in env config (not code) so the image stays free of personal data.
    contact_name: str = ""
    contact_email: str = ""

    # CV content delivery. When set (gs://<bucket>/<object>), the CV document
    # is fetched from a private GCS bucket instead of the local file — the
    # image ships without personal data. The object is re-checked every
    # cv_refresh_seconds via its generation number, so uploading a new file
    # goes live without a redeploy. Runtime refresh failures keep serving the
    # last good payload; startup failures abort boot.
    cv_data_gcs_uri: str = ""
    cv_refresh_seconds: int = 30

    # Client-IP strategy for rate limiting behind a reverse proxy.
    # - client_ip_xff_entry > 0: Nth entry of X-Forwarded-For counted from the
    #   right (Cloud Run recipe: 2 — GFE appends itself, so the penultimate
    #   entry is the real client and cannot be spoofed).
    # - client_ip_header: raw single-value header (nginx recipe: X-Real-IP).
    # Both unset -> socket peer address.
    client_ip_xff_entry: int = 0
    client_ip_header: str = ""

    # Set on platforms where the socket peer is a local proxy hop rather than
    # the client (e.g. Cloud Run sees 127.0.0.1 for every request). Disables
    # loopback-peer exemptions so rate limits and failban stay effective.
    trust_proxy: bool = False

    # Static access lists (comma-separated IPs/CIDRs). Empty string disables.
    # allowed_ips acts as a whitelist: when set, only listed clients may connect.
    # The *_FILE variants point to text files with one IP/CIDR per line
    # ('#' comments allowed) and are merged with the inline value. Large geo
    # lists must use the file form (env vars are capped at ~128KB by execve).
    blocked_ips: str = ""
    allowed_ips: str = ""
    blocked_ips_file: Path | None = None
    allowed_ips_file: Path | None = None

    # Scheduled availability window (evaluated in service_timezone, default UTC).
    # Empty start/end = always open. Overnight windows (start > end) supported.
    # service_days: comma-separated weekday names (mon..sun); empty = every day.
    # Days only apply when hours are set.
    service_hours_start: str = ""
    service_hours_end: str = ""
    service_days: str = ""
    service_timezone: str = ""

    # Dynamic ban (fail2ban-lite): N rate-limit violations within the window
    # triggers a temporary ban. threshold=0 disables.
    failban_threshold: int = 0
    failban_window_seconds: int = 900
    failban_ban_seconds: int = 1800
    failban_max_tracked: int = 10000

    # Bearer-token auth for POST /cv/tailor. Single-operator use: ONE token,
    # fail-closed. TAILOR_BEARER_TOKEN_FILE is preferred for production so
    # the secret never lands in shell history or process listings; the inline
    # value is a convenience for dev. When both are set, the file wins. Read
    # once at startup; rotate by restarting the service. Enforced only by
    # TailorAuthMiddleware — does not affect any other route.
    tailor_bearer_token: str = ""
    tailor_bearer_token_file: Path | None = None

    # Phase-1c Auth secrets.
    jwt_signing_key: str = ""
    refresh_token_pepper: str = ""

    # Skill bank used by POST /cv/tailor and the MCP match_jd tool. Lazy-loaded
    # on first use and memoized per (path, mtime). Defaults are dev-friendly;
    # point CV_BASELINE_PATH at the bank and CV_TAILORED_DIR at the directory
    # that receives cv_tailored-<timestamp>.json revision files.
    cv_baseline_path: Path = Path("data/cv_baseline.json")
    cv_tailored_dir: Path = Path("data/tailored")


settings = Settings()
