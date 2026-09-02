from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    port: int = 8080

    # This service is a separate Cloud Run workload from api-core (the
    # portfolio host), so "Back to portfolio" needs an absolute URL — a
    # relative "/" 404s here in both dev and prod. Empty = same-origin, for
    # the case where this router is ever mounted into api-core instead of
    # deployed standalone.
    portfolio_base_url: str = ""


settings = Settings()
