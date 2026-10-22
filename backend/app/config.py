"""
config.py - NutriSnap backend configuration (pydantic-settings).
All environment variables are declared here. Constants come from
category_rules.json; never hard-code scoring values in this file.
"""
from __future__ import annotations

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configurable env vars (Appendix C, ARCHITECTURE.md)."""

    model_config = SettingsConfigDict(
        env_file=".env",
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
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"

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


settings = Settings()
