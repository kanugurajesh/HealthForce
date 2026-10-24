"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_prefix="HF_", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'healthforce.db').as_posix()}"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"

    # Auth. The default secret is only acceptable outside production (enforced in main.py).
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_ttl_minutes: int = 8 * 60
    cookie_secure: bool = False

    # AI extraction. "mock" is a deterministic, offline heuristic extractor that is
    # always labelled as such in the UI; "groq" calls gpt-oss-120b on Groq.
    extraction_provider: Literal["mock", "groq"] = "mock"
    groq_model: str = "openai/gpt-oss-120b"
    groq_reasoning_effort: Literal["low", "medium", "high"] = "medium"
    groq_timeout_seconds: float = 90.0
    # Read from GROQ_API_KEY (standard name) or HF_GROQ_API_KEY; never sent to the browser or logged.
    groq_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("GROQ_API_KEY", "HF_GROQ_API_KEY"))

    # Credential verification. There is no real registry integration; "simulated"
    # enables a clearly-labelled demo verification action.
    verification_mode: Literal["disabled", "simulated"] = "simulated"

    max_upload_bytes: int = 5 * 1024 * 1024
    max_job_attempts: int = 3
    expiring_soon_days: int = 60
    run_worker: bool = True
    worker_poll_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
