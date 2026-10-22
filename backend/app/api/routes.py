"""
routes.py - API route definitions for NutriSnap (ARCHITECTURE §9).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi import Query

from app.config import settings
from app.core.knowledge_base import KnowledgeBase
from app.core.ml.manager import get_model
from app.core.scoring import analyze
from app.core.database import demo_queries, history, record_scan, stats
from app.core.parser import parse
from app.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    HealthFeatures,
    HealthResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Knowledge base singleton — loaded at startup via main.py lifespan.
_kb: KnowledgeBase | None = None


def set_knowledge_base(kb: KnowledgeBase) -> None:
    global _kb
    _kb = kb


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """
    Returns application health including ML status and feature flags.
    ml_status is one of: ready, loading, disabled, error.
    """
    kb_version = _kb.version if _kb else 0
    kb_entries = len(_kb.entries) if _kb else 0
    model = get_model()
    ml_status = model.status
    ml_error = getattr(model, "error_reason", None)
    if ml_status == "error" and ml_error == "selftest_failed":
        ml_status = "error: selftest_failed"

    return HealthResponse(
        status="ok",
        ml_status=ml_status,
        ml_error=ml_error,
        backend=settings.nova_backend,
        kb_version=kb_version,
        kb_entries=kb_entries,
        features=HealthFeatures(
            nutriscore=settings.feature_nutriscore,
            hindi_ml=settings.ml_hindi_supported,
        ),
    )


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_endpoint(request: AnalyzeRequest) -> AnalyzeResponse:
    """
    Analyze packaged food ingredients text.
    Executes the full scoring lifecycle per ARCHITECTURE §4 and §9.2.
    """
    result = analyze(
        text=request.ingredients_text,
        profile=request.profile,
        force_mode=request.force_mode,
        kb=_kb,
    )
    if result.status == "ok":
        record_scan(result, parse(request.ingredients_text))
    return result


@router.get("/history")
def history_endpoint(limit: int = Query(default=50, ge=1, le=100)):
    return {"items": history(limit)}


@router.get("/stats")
def stats_endpoint():
    return stats()


@router.get("/queries")
def queries_endpoint():
    return {"queries": demo_queries()}
