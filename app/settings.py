from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    cv_data_path: Path = Path("data/cv.json")
    port: int = 8080


settings = Settings()
