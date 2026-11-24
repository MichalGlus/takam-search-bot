"""Configuration. All values come from environment variables or `.env`; no secrets in code."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TAKAM_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Source site
    base_url: str = "https://takam.mof.gov.il/"
    chapters: list[int] = [1]
    request_timeout: float = 60.0
    request_delay: float = 0.5
    max_retries: int = 3

    # Storage
    data_dir: Path = PROJECT_ROOT / "data"

    # Retrieval
    search_top_k: int = 8

    # LLM (optional). Any provider supported by LangChain's init_chat_model.
    llm_enabled: bool = True
    llm_provider: str = "google_genai"
    llm_model: str = "gemini-3.5-flash"
    # Same provider, used when the primary model fails (overload, timeout). Empty disables.
    llm_fallback_model: str = "gemini-3.5-flash-lite"
    llm_api_key: SecretStr | None = None
    llm_timeout: float = 25.0

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def docs_dir(self) -> Path:
        return self.raw_dir / "docs"

    @property
    def manifest_path(self) -> Path:
        return self.raw_dir / "manifest.json"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "index.db"

    @property
    def eval_path(self) -> Path:
        return self.data_dir / "eval.jsonl"

    @property
    def llm_available(self) -> bool:
        """True when an LLM is enabled and a credential is configured for its provider."""
        if not self.llm_enabled:
            return False
        if self.llm_api_key and self.llm_api_key.get_secret_value():
            return True
        env_vars = PROVIDER_KEY_ENV.get(self.llm_provider)
        if env_vars is None:  # e.g. a local model server that needs no key
            return True
        return any(os.environ.get(v) for v in env_vars)


# Standard key variables read by the LangChain integrations themselves.
PROVIDER_KEY_ENV: dict[str, tuple[str, ...]] = {
    "google_genai": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "azure_openai": ("AZURE_OPENAI_API_KEY",),
    "mistralai": ("MISTRAL_API_KEY",),
}


@lru_cache
def get_settings() -> Settings:
    return Settings()
