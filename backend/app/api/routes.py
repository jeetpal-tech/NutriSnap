"""
routes.py - API route definitions for NutriSnap (ARCHITECTURE §9).
"""
from __future__ import annotations

import logging
import asyncio
from email import policy
from email.parser import BytesParser

from fastapi import APIRouter, HTTPException, Query, Request

from app.config import settings
from app.core.knowledge_base import KnowledgeBase
from app.core.ml.manager import get_model
from app.core.scoring import analyze
from app.core.database import demo_queries, history, record_scan, stats
from app.core.parser import parse
from app.core import gemini
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
        gemini_status="configured" if settings.gemini_api_key.strip() else "missing_key",
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
    return _scan_text(request.ingredients_text, "paste", request.profile, request.force_mode)


def _scan_text(text: str, source: str, profile=None, force_mode: str = "auto", detected_text: str | None = None):
    result = analyze(text=text, profile=profile, force_mode=force_mode, kb=_kb)
    result.source = source
    result.detected_text = detected_text
    if result.status == "ok":
        tokens = parse(text)
        names = [token.raw for token in tokens]
        fallback_names = [item.canonical or item.name for item in result.ingredients]
        try:
            enrichment = gemini.analyze_ingredient_list(text, names, fallback_names=fallback_names, kb=_kb)
            result.ingredient_info = enrichment["ingredient_info"]
            result.alternatives = enrichment["alternatives"]
            result.ingredient_analysis_source = enrichment["source"]
        except Exception:
            # Enrichment is optional and must never affect the score or response availability.
            result.ingredient_info = []
            result.alternatives = []
            result.ingredient_analysis_source = "unavailable"
        record_scan(result, tokens, source=source)
    return result


@router.post("/scan-image")
async def scan_image(request: Request):
    """Read one multipart image entirely in memory, OCR it, then use the normal scorer."""
    max_bytes = 5 * 1024 * 1024
    try:
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(status_code=413, detail="Image must be 5 MB or smaller.")
            chunks.append(chunk)
        body = b"".join(chunks)
        content_type = request.headers.get("content-type", "")
        wrapper = (f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii") + body)
        message = BytesParser(policy=policy.default).parsebytes(wrapper)
        if not message.is_multipart():
            raise HTTPException(status_code=400, detail="Expected a multipart image upload.")
        image_bytes = None
        mime = "image/jpeg"
        for part in message.iter_parts():
            field = part.get_param("name", header="content-disposition")
            if field in {"file", "image"}:
                image_bytes = part.get_payload(decode=True)
                mime = part.get_content_type()
                break
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Upload an image in the file field.")
        if not mime.startswith("image/"):
            raise HTTPException(status_code=415, detail="Upload must be an image.")
        if not settings.gemini_api_key.strip():
            return {"status":"ocr_unavailable","source":"camera","message":"Image reading needs GEMINI_API_KEY. Paste the ingredient text instead."}
        extracted = await asyncio.to_thread(gemini.extract_ingredients, image_bytes, mime)
        del image_bytes, body, chunks
        if not extracted:
            return {"status":"ocr_unavailable","source":"camera","message":"Could not read this image. Paste the ingredient text instead."}
        if not extracted["found"] or not extracted["ingredients_text"].strip():
            return {"status":"no_ingredients_found","source":"camera","detected_text":"","message":"No ingredient list was found in the image."}
        result = await asyncio.to_thread(_scan_text, extracted["ingredients_text"], "camera", None, "auto", extracted["ingredients_text"])
        if result.status == "ok":
            return result
        return {**result.model_dump(),"source":"camera","detected_text":extracted["ingredients_text"],"message":result.message}
    except HTTPException:
        raise
    except Exception:
        return {"status":"ocr_unavailable","source":"camera","message":"Image scanning is temporarily unavailable. Paste the ingredient text instead."}


@router.get("/history")
def history_endpoint(limit: int = Query(default=50, ge=1, le=100)):
    return {"items": history(limit)}


@router.get("/stats")
def stats_endpoint():
    return stats()


@router.get("/queries")
def queries_endpoint():
    return {"queries": demo_queries()}
