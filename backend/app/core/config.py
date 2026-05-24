from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    deepseek_api_key: str = Field(..., description="DeepSeek API 密钥")
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    database_url: str = Field(..., description="PostgreSQL 异步连接串")

    redis_url: str = "redis://localhost:6379/0"

    github_token: str = ""           # Personal Access Token / GitHub App token
    github_webhook_secret: str = ""
    gitlab_webhook_secret: str = ""
    gitee_webhook_secret: str = ""

    app_env: Literal["development", "production", "test"] = "development"
    secret_key: str = "change_this_to_a_random_string"

    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
