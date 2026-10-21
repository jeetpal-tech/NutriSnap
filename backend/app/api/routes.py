"""
routes.py - API route definitions.
M0: only /api/health is implemented.
M3: /api/analyze will be wired here.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.config import settings
from app.core.knowledge_base import KnowledgeBase
from app.schemas import HealthFeatures, HealthResponse

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
    ml_status is 'disabled' until M3 (no model loaded yet).
    """
    kb_version = _kb.version if _kb else 0
    kb_entries = len(_kb.entries) if _kb else 0

    return HealthResponse(
        status="ok",
        ml_status="disabled",  # M3 will wire the real ML status
        backend=settings.nova_backend,
        kb_version=kb_version,
        kb_entries=kb_entries,
        features=HealthFeatures(
            nutriscore=settings.feature_nutriscore,
            hindi_ml=settings.ml_hindi_supported,
        ),
    )
