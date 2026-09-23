"""
Centralized application configuration (TASK-204).

All settings come from environment variables / .env via pydantic-settings.
Hardcoded thresholds elsewhere in the codebase must read from here.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    llm_timeout_s: float = 60.0

    # --- CORS / server ---
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    log_level: str = "INFO"

    # --- Upload limits (TASK-204: migrated from hardcoded values) ---
    upload_max_bytes: int = 10 * 1024 * 1024  # 10MB
    upload_cache_ttl_s: int = 3600  # uploaded CSV cache: 1 hour

    # --- Session lifecycle ---
    session_cleanup_interval_s: int = 3600  # cleanup loop period: 1 hour
    session_idle_ttl_s: int = 24 * 3600  # idle eviction threshold: 24 hours

    # --- Rate limiting / circuit breaker (TASK-205) ---
    rate_limit_per_minute: int = 20  # per-IP chat/stream calls per minute
    breaker_failure_threshold: int = 3  # consecutive LLM failures before open
    breaker_cooldown_s: int = 60  # breaker open duration

    # --- Agent loop (TASK-203) ---
    agent_max_steps: int = 5
    # Same action may be retried after a failure (e.g. train before load),
    # but never more than this many times in one command — prevents the
    # "failed action spins forever" loop.
    agent_max_action_retries: int = 2

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
