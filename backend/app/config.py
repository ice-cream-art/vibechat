from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "development"
    llm_provider: str = "demo"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"

    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_model: str = "claude-sonnet-4-20250514"

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cors_origin_regex: str = r"https://.*\.trycloudflare\.com"
    match_threshold: float = Field(default=0.56, ge=0, le=1)

    kv_rest_api_url: str = ""
    kv_rest_api_token: str = ""
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def redis_url(self) -> str:
        return self.kv_rest_api_url or self.upstash_redis_rest_url

    @property
    def redis_token(self) -> str:
        return self.kv_rest_api_token or self.upstash_redis_rest_token


@lru_cache
def get_settings() -> Settings:
    return Settings()
