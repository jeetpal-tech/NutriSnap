"""
schemas.py - Pydantic v2 request / response models for the NutriSnap API.
Shapes follow ARCHITECTURE.md section 9.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# ── Shared sub-models ──────────────────────────────────────────────────────────

class ProfileRequest(BaseModel):
    conditions: list[Literal["diabetes", "hypertension", "high_cholesterol"]] = Field(
        default_factory=list
    )


class NutritionRequest(BaseModel):
    """Per-100 g nutrition inputs (all optional; see ARCHITECTURE 16.2)."""
    basis: Literal["per_100g"] = "per_100g"
    category: Literal["food", "beverage", "fat_oil_nut_seed"] = "food"
    energy_kcal: float | None = None
    protein_g: float | None = None
    carbohydrate_g: float | None = None
    sugars_g: float | None = None
    added_sugars_g: float | None = None
    fat_g: float | None = None
    saturated_fat_g: float | None = None
    trans_fat_g: float | None = None
    fibre_g: float | None = None
    sodium_mg: float | None = None
    fruit_veg_legume_nut_pct: float | None = None
    serving_size_g: float | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> "NutritionRequest":
        if self.sugars_g is not None and self.carbohydrate_g is not None:
            if self.sugars_g > self.carbohydrate_g:
                raise ValueError("sugars_g must be <= carbohydrate_g")
        if self.saturated_fat_g is not None and self.fat_g is not None:
            if self.saturated_fat_g > self.fat_g:
                raise ValueError("saturated_fat_g must be <= fat_g")
        return self


# ── Request ────────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    ingredients_text: str = Field(..., min_length=1, max_length=4000)
    profile: ProfileRequest | None = None
    lang: Literal["en", "hi"] = "en"
    nutrition: NutritionRequest | None = None
    force_mode: Literal["auto", "rules"] = "auto"


# ── Response sub-models ────────────────────────────────────────────────────────

class NovaResult(BaseModel):
    top: int
    confidence: float
    probs: dict[str, float]
    model_id: str
    latency_ms: int


class NovaBadge(BaseModel):
    group: int | None
    label: str | None
    source: Literal["model", "rule_estimate", "unavailable"]
    confidence: float | None = None
    basis: list[str] = Field(default_factory=list)


class NutriscoreResult(BaseModel):
    status: Literal["computed", "missing_inputs", "not_provided", "disabled"]
    grade: str | None = None
    points: int | None = None
    algorithm: str | None = None
    category: str | None = None
    components: dict[str, Any] | None = None
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class LanguageResult(BaseModel):
    detected: Literal["latin", "devanagari", "mixed"]
    ml_input: Literal["full", "latin_only"]


class FlagSummary(BaseModel):
    flag: str
    label: str
    severity: Literal["high", "medium", "low"]


class IngredientResult(BaseModel):
    position: int
    raw: str
    name: str
    matched: bool
    kb_id: str | None = None
    canonical: str | None = None
    flag: str | None = None
    risk: Literal["low", "medium", "high", "neutral", "unknown"]
    points: float
    explanation: str | None = None
    source: Any | None = None
    verified: bool = False


class ProfileEffect(BaseModel):
    condition: str
    flag: str
    multiplier: float


class SwapTip(BaseModel):
    flag: str
    tip: str | None = None


class SafetyCapApplied(BaseModel):
    reason: str
    max_score: int


# ── Main response ──────────────────────────────────────────────────────────────

class AnalyzeResponse(BaseModel):
    status: Literal["ok", "insufficient_input", "not_food_text"]
    message: str | None = None
    score: int | None = None
    band: Literal["Low Risk", "Moderate Risk", "High Risk"] | None = None
    scoring_method: Literal["ml_assisted", "rule_based"] | None = None
    fallback_reason: str | None = None
    rule_score: int | None = None
    ml_score: int | None = None
    nova: NovaResult | None = None
    kb_coverage: float | None = None
    low_coverage_warning: bool | None = None
    nova_badge: NovaBadge | None = None
    nutriscore: NutriscoreResult | None = None
    language: LanguageResult | None = None
    flags: list[FlagSummary] = Field(default_factory=list)
    ingredients: list[IngredientResult] = Field(default_factory=list)
    profile_effects: list[ProfileEffect] = Field(default_factory=list)
    caps_applied: list[SafetyCapApplied] = Field(default_factory=list)
    swap_tips: list[SwapTip] = Field(default_factory=list)
    disclaimer: str | None = None
    attribution: str | None = None
    warnings: list[str] = Field(default_factory=list)
    source: Literal["camera", "paste"] | None = None
    detected_text: str | None = None
    ingredient_info: list[dict[str, Any]] = Field(default_factory=list)
    ingredient_analysis_source: Literal["gemini", "database_fallback", "unavailable"] | None = None
    alternatives: list[dict[str, Any]] = Field(default_factory=list)


# ── Health response ────────────────────────────────────────────────────────────

class HealthFeatures(BaseModel):
    nutriscore: bool
    hindi_ml: bool


class HealthResponse(BaseModel):
    status: Literal["ok"]
    ml_status: str
    ml_error: str | None = None
    gemini_status: Literal["configured", "missing_key"] = "missing_key"
    backend: str
    kb_version: int
    kb_entries: int
    features: HealthFeatures
