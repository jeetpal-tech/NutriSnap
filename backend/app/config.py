"""
config.py - NutriSnap backend configuration (pydantic-settings).
All environment variables are declared here. Constants come from
category_rules.json; never hard-code scoring values in this file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configurable env vars (Appendix C, ARCHITECTURE.md)."""

    model_config = SettingsConfigDict(
        # Resolve the ignored backend/.env from the repository, regardless of
        # whether uvicorn is launched from the project root or backend folder.
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── ML feature switches ────────────────────────────────────────────────
    ml_enabled: bool = True
    nova_backend: Literal["hf_hsilvosa", "minilm_head"] = "minilm_head"
    nova_model_dir: str = "backend/models/minilm-head"
    nova_model_revision: str = "f252e3546650954596ff7e5926aab4559c433909"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    gemini_timeout_s: float = 30.0
    gemini_max_attempts: int = 3
    gemini_backoff_s: float = 0.35
    gemini_cache_ttl_s: int = 30 * 24 * 60 * 60

    # ── Gate thresholds ────────────────────────────────────────────────────
    ml_timeout_s: float = 3.0
    ml_min_confidence: float = 0.60
    ml_nova2_min_confidence: float = 0.80
    ml_min_margin: float = 0.15
    ml_max_optimistic_gap: int = 25
    ml_max_pessimistic_gap: int = 45

    # ── Language / Hindi ───────────────────────────────────────────────────
    ml_hindi_supported: bool = False

    # ── Feature flags (backend) ────────────────────────────────────────────
    feature_nutriscore: bool = False
    show_unverified_badge: bool = True

    # ── CORS ───────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173"
    cors_origin_regex: str = ""

    # ── Runtime / persistence ───────────────────────────────────────────────
    database_path: str = ""
    session_cookie_name: str = "nutrisnap_session"
    session_cookie_max_age_s: int = 60 * 60 * 24 * 30
    session_cookie_secure: bool = False
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    production: bool = False
    enable_api_docs: bool = False

    # ── Logging ────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: str) -> str:  # noqa: N805
        # Store as-is; parsed by main.py when building the middleware list.
        return v

    def cors_origins_list(self) -> list[str]:
        """Return CORS_ORIGINS as a list (comma-separated values supported)."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def database_path_value(self) -> Path:
        """Return an absolute database path independent of the launch cwd."""
        if self.database_path.strip():
            path = Path(self.database_path).expanduser()
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[1] / path
            return path.resolve()
        return Path(__file__).resolve().parents[1] / "data" / "nutrisnap.db"


settings = Settings()
