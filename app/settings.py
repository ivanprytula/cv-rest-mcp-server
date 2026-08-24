from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    cv_data_path: Path = Path("data/cv.json")
    port: int = 8080

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


settings = Settings()
