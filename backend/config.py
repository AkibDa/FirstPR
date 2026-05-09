from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import logging
import os
from dataclasses import dataclass, field


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    app_env: str = field(
        default_factory=lambda: _env("APP_ENV", "development").lower()
    )

    vllm_base_url: str   = field(default_factory=lambda: _env("VLLM_BASE_URL"))
    cloud_llm_model: str = field(
        default_factory=lambda: _env(
            "CLOUD_LLM_MODEL", "Qwen/Qwen2.5-Coder-7B-Instruct"
        )
    )
    ollama_base_url: str = field(
        default_factory=lambda: _env("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    local_llm_model: str = field(
        default_factory=lambda: _env("LOCAL_LLM_MODEL", "qwen2.5-coder:1.5b")
    )

    cloud_embed_url: str   = field(default_factory=lambda: _env("CLOUD_EMBED_URL"))
    cloud_embed_model: str = field(
        default_factory=lambda: _env("CLOUD_EMBED_MODEL", "BAAI/bge-large-en-v1.5")
    )
    local_embed_model: str = field(
        default_factory=lambda: _env("LOCAL_EMBED_MODEL", "BAAI/bge-base-en-v1.5")
    )

    cloud_rerank_url: str   = field(default_factory=lambda: _env("CLOUD_RERANK_URL"))
    local_rerank_model: str = field(
        default_factory=lambda: _env(
            "LOCAL_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
        )
    )

    redis_url: str        = field(
        default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379/0")
    )
    chroma_path: str      = field(
        default_factory=lambda: _env("CHROMA_PATH", "./chroma_db")
    )
    llm_timeout: int      = field(
        default_factory=lambda: _env_int("LLM_TIMEOUT", 120)
    )
    embed_batch_size: int = field(
        default_factory=lambda: _env_int("EMBED_BATCH_SIZE", 32)
    )
    max_repo_mb: int      = field(
        default_factory=lambda: _env_int("MAX_REPO_MB", 300)
    )
    log_level: str        = field(
        default_factory=lambda: _env("LOG_LEVEL", "INFO").upper()
    )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def llm_base_url(self) -> str:
        """Active LLM base URL for the current runtime mode."""
        return self.vllm_base_url if self.is_production else self.ollama_base_url

    @property
    def llm_model(self) -> str:
        return self.cloud_llm_model if self.is_production else self.local_llm_model

    @property
    def embed_model(self) -> str:
        return self.cloud_embed_model if self.is_production else self.local_embed_model

    def validate(self) -> None:
        """Raise ValueError for missing required production variables."""
        if not self.is_production:
            return
        missing = [
            k for k, v in {
                "VLLM_BASE_URL":    self.vllm_base_url,
                "CLOUD_EMBED_URL":  self.cloud_embed_url,
                "CLOUD_RERANK_URL": self.cloud_rerank_url,
            }.items()
            if not v
        ]
        if missing:
            raise ValueError(
                f"[FirstPR] Production mode requires: {', '.join(missing)}"
            )


settings = Settings()


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
