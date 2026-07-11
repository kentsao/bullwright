"""12-factor settings; every knob documented in .env.example."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BW_", env_file=".env", extra="ignore")

    env: str = "dev"
    db_url: str = "sqlite:///data/bullwright.db"
    api_host: str = "127.0.0.1"
    api_port: int = 8600
    log_level: str = "info"
    git_sha: str = "dev"

    # Limits (docs/API.md §6). Tests shrink these via env.
    max_request_bytes: int = 1_048_576  # 1 MiB → 413
    max_report_body_bytes: int = 262_144  # 256 KiB → 422
    rate_limit_reads_per_min: int = 60
    rate_limit_writes_per_min: int = 10

    billing_enabled: bool = False

    def env_key_label(self) -> str:
        """bw_test_ keys in test env, bw_live_ otherwise (docs/API.md §3)."""
        return "test" if self.env == "test" else "live"


@lru_cache
def settings() -> Settings:
    return Settings()
