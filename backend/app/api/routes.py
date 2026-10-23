"""Customer-facing API routes.

Only scoped scan operations are public.  SQL/statistics helpers remain local
Python functions for the professor-facing demonstrations and are not routes.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import uuid
from email import policy
from email.parser import BytesParser
from typing import Any, Literal, cast

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from app.config import settings
from app.core import gemini
from app.core.database import (
    DB_PATH,
    IdempotencyConflict,
    PersistenceError,
    ScanInProgress,
    clear_history,
    create_scan,
    delete_scan,
    fail_scan,
    finalize_scan,
    get_scan,
    history,
    record_provider_attempt,
    record_scan,
    request_fingerprint,
    reconcile_interrupted,
    transition_scan,
)
from app.core.knowledge_base import KnowledgeBase
from app.core.ml.manager import get_model
from app.core.parser import parse
from app.core.scoring import analyze
from app.schemas import AnalyzeRequest, AnalyzeResponse, HealthFeatures, HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
_kb: KnowledgeBase | None = None


def set_knowledge_base(kb: KnowledgeBase) -> None:
    global _kb
    _kb = kb


def _db_path():
    return settings.database_path_value() if hasattr(settings, "database_path_value") else DB_PATH


def _request_id(request: Request) -> str:
    value = request.headers.get("x-request-id", "")
    if len(value) <= 80 and value.replace("-", "").replace("_", "").isalnum():
        return value or uuid.uuid4().hex
    return uuid.uuid4().hex


def _session_id(request: Request, response: Response) -> str:
    cookie_name = settings.session_cookie_name
    value = request.cookies.get(cookie_name)
    if not value or len(value) < 32 or len(value) > 256:
        value = secrets.token_urlsafe(32)
        response.set_cookie(
            cookie_name,
            value,
            max_age=settings.session_cookie_max_age_s,
            httponly=True,
            secure=bool(settings.session_cookie_secure or settings.production),
            samesite=settings.session_cookie_samesite,
            path="/",
        )
    return value


def _check_origin(request: Request) -> None:
    """Reject cross-site mutations when a browser sends an Origin header."""
    origin = request.headers.get("origin")
    if not origin:
        return
    allowed = set(settings.cors_origins_list())
    if origin in allowed:
        return
    if settings.cors_origin_regex:
        import re

        if re.fullmatch(settings.cors_origin_regex, origin):
            return
    raise HTTPException(status_code=403, detail="origin_not_allowed")


def _safe_result_metadata(result: AnalyzeResponse, accepted: dict[str, Any], *, save_status: str, status: str, completeness: str | None) -> AnalyzeResponse:
    result.scan_id = accepted.get("public_id")
    result.request_id = accepted.get("request_id")
    result.scan_status = cast(Literal[
        "received", "extracting", "awaiting_confirmation", "analyzing", "completed",
        "completed_limited", "failed", "cancelled", "interrupted"
    ], status)
    result.persisted = save_status in {"saved", "reused"}
    result.save_status = save_status  # type: ignore[assignment]
    result.completeness = completeness  # type: ignore[assignment]
    if result.nova is not None:
        # Model identity and latency are operational details, not customer copy.
        result.nova.model_id = None
        result.nova.latency_ms = None
    return result


def _processing_response(accepted: dict[str, Any]) -> AnalyzeResponse:
    return AnalyzeResponse(
        status="processing",
        message="This scan is already being processed.",
        message_code="scan_in_progress",
        scan_id=accepted.get("public_id"),
        request_id=accepted.get("request_id"),
        scan_status="analyzing",
        persisted=True,
        save_status="reused",
    )


def _public_enrichment(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Keep customer enrichment useful without exposing provider/cache metadata."""
    public: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        row = {
            "name": str(item["name"]),
            "what_it_is": item.get("what_it_is"),
            "health_note": item.get("health_note"),
            "risk_level": item.get("risk_level", item.get("concern_level", "unknown")),
            "concern_level": item.get("concern_level", item.get("risk_level", "unknown")),
            "verified": bool(item.get("verified")),
            "ai_generated": bool(item.get("ai_generated")),
        }
        public.append(row)
    return public


def _public_alternatives(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Return generic alternatives without provider model/cache provenance."""
    public: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("type") or not item.get("reason"):
            continue
        public.append(
            {
                "type": str(item["type"]),
                "reason": str(item["reason"]),
                "ai_generated": bool(item.get("ai_generated")),
            }
        )
    return public


def _reuse_response(accepted: dict[str, Any]) -> AnalyzeResponse | None:
    if not accepted.get("reused") or not accepted.get("result"):
        return None
    try:
        result = AnalyzeResponse.model_validate(accepted["result"])
    except Exception:
        return None
    return _safe_result_metadata(
        result,
        accepted,
        save_status="reused",
        status=accepted.get("status", "completed"),
        completeness=accepted.get("completeness"),
    )


def _scan_text(
    text: str,
    source: Literal["camera", "upload", "paste"],
    profile: Any = None,
    force_mode: Literal["auto", "rules"] = "auto",
    detected_text: str | None = None,
    *,
    request: Request | None = None,
    response: Response | None = None,
    idempotency_key: str | None = None,
    parent_scan_id: int | None = None,
) -> AnalyzeResponse:
    """Accept, analyze, enrich, and atomically finalize one scan lifecycle."""
    if request is not None:
        session_id = _session_id(request, response or Response())
        request_id = _request_id(request)
    else:
        session_id = None
        request_id = uuid.uuid4().hex
    idempotency_key = (idempotency_key or uuid.uuid4().hex)[:128]
    fingerprint = request_fingerprint(text, profile.model_dump(mode="json") if hasattr(profile, "model_dump") else profile, force_mode)
    tokens = parse(text)
    result: AnalyzeResponse | None = None
    try:
        accepted = create_scan(
            session_id=session_id,
            idempotency_key=idempotency_key,
            request_id=request_id,
            request_fingerprint_value=fingerprint,
            source=source,
            n_tokens=len(tokens),
            path=_db_path(),
            parent_scan_id=parent_scan_id,
            kb_version=_kb.version if _kb else 0,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail="idempotency_conflict") from exc
    except ScanInProgress as exc:
        # Fetching the existing row is deliberately scoped by the same session
        # and key; no provider work is repeated.
        if exc.scan is not None:
            return _processing_response({
                "public_id": exc.scan["public_id"],
                "request_id": exc.scan["request_id"],
                "status": exc.scan["status"],
            })
        raise HTTPException(status_code=409, detail="scan_in_progress")
    except Exception as exc:
        logger.warning("Initial scan persistence failed", exc_info=True)
        raise HTTPException(status_code=503, detail="scan_not_saved") from exc

    reused = _reuse_response(accepted)
    if reused is not None:
        return reused
    if accepted.get("reused") and accepted.get("status") not in {"received", "analyzing"}:
        return _processing_response(accepted)

    scan_private_id = accepted["_scan_id"]
    try:
        transition_scan(scan_private_id, "analyzing", path=_db_path())
        result = analyze(text=text, profile=profile, force_mode=force_mode, kb=_kb)
        result.source = cast(Literal["camera", "paste"], "camera" if source in {"camera", "upload"} else "paste")
        result.detected_text = detected_text
        provider_category = "not_requested"
        provider_attempts = 0

        if result.status == "ok":
            names = [token.raw for token in tokens]
            fallback_names = [item.canonical or item.name for item in result.ingredients]
            try:
                enrichment = gemini.analyze_ingredient_list(
                    text,
                    names,
                    fallback_names=fallback_names,
                    kb=_kb,
                    path=_db_path(),
                )
                result.ingredient_info = _public_enrichment(enrichment.get("ingredient_info"))
                result.alternatives = _public_alternatives(enrichment.get("alternatives"))
                result.ingredient_analysis_source = enrichment["source"]
                provider_category = enrichment.get("provider_category") or ("success" if settings.gemini_api_key.strip() else "configuration_missing")
                provider_attempts = int(enrichment.get("provider_attempts") or (1 if settings.gemini_api_key.strip() else 0))
                if any(item.get("risk_level") == "unknown" for item in result.ingredient_info):
                    result.warnings.append("Some ingredients could not be assessed.")
            except Exception:
                logger.warning("Ingredient enrichment failed", exc_info=True)
                result.ingredient_info = []
                result.alternatives = []
                result.ingredient_analysis_source = "unavailable"
                result.warnings.append("Some ingredients could not be assessed.")
                provider_category = "provider_error"
        else:
            provider_category = "not_applicable"

        if settings.gemini_api_key.strip() or result.status == "ok":
            try:
                record_provider_attempt(
                    scan_private_id,
                    operation="ingredient_analysis",
                    attempt_number=max(1, provider_attempts),
                    outcome=provider_category,
                    model=settings.gemini_model if settings.gemini_api_key.strip() else None,
                    attempted=bool(settings.gemini_api_key.strip()),
                    path=_db_path(),
                )
            except Exception:
                logger.warning("Provider-attempt persistence failed", exc_info=True)

        has_unknown_enrichment = any(
            item.get("risk_level") == "unknown" for item in (result.ingredient_info or [])
        )
        limited = (
            result.status != "ok"
            or result.ingredient_analysis_source in {"mixed", "unavailable"}
            or has_unknown_enrichment
            or bool(result.low_coverage_warning)
        )
        final_status = "completed_limited" if limited else "completed"
        result = _safe_result_metadata(
            result,
            accepted,
            save_status="saved",
            status=final_status,
            completeness="limited" if limited else "complete",
        )
        try:
            finalize_scan(
                scan_private_id,
                result,
                tokens,
                path=_db_path(),
                kb_version=_kb.version if _kb else 0,
                completeness="limited" if limited else "complete",
            )
        except Exception as exc:
            logger.warning("Final scan persistence failed", exc_info=True)
            try:
                fail_scan(scan_private_id, reason="persistence_failed", path=_db_path())
            except Exception:
                logger.warning("Could not record scan persistence failure", exc_info=True)
            return _safe_result_metadata(result, accepted, save_status="save_failed", status="failed", completeness="limited")
        return result
    except HTTPException:
        raise
    except PersistenceError:
        try:
            fail_scan(scan_private_id, reason="persistence_failed", path=_db_path())
        except Exception:
            logger.warning("Could not record scan persistence failure", exc_info=True)
        # Scoring may be valid, but the caller must not be told it was saved.
        if result is not None:
            return _safe_result_metadata(result, accepted, save_status="save_failed", status="failed", completeness="limited")
        raise HTTPException(status_code=503, detail="scan_not_saved")
    except Exception:
        logger.exception("Scan processing failed")
        try:
            fail_scan(scan_private_id, reason="scan_failed", path=_db_path())
        except Exception:
            logger.warning("Could not record scan failure", exc_info=True)
        raise HTTPException(status_code=503, detail="scan_unavailable")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Minimal liveness/readiness response; no provider probe or diagnostics."""
    model = get_model()
    return HealthResponse(
        status="ok",
        ml_ready=model.status == "ready",
        ml_status=model.status,
        ml_error=None,
        gemini_status="configured" if settings.gemini_api_key.strip() else "missing_key",
        backend=settings.nova_backend,
        features=HealthFeatures(
            nutriscore=settings.feature_nutriscore,
            hindi_ml=settings.ml_hindi_supported,
        ),
    )


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_endpoint(
    request: AnalyzeRequest,
    http_request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AnalyzeResponse:
    _check_origin(http_request)
    return _scan_text(
        request.ingredients_text,
        "paste",
        request.profile,
        request.force_mode,
        request= http_request,
        response=response,
        idempotency_key=idempotency_key,
    )


@router.post("/scan-image")
async def scan_image(
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    source: str = Query(default="camera", pattern="^(camera|upload)$"),
):
    """Read one multipart image in memory, then use the normal scorer."""
    _check_origin(request)
    max_bytes = 5 * 1024 * 1024
    try:
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(status_code=413, detail="image_too_large")
            chunks.append(chunk)
        body = b"".join(chunks)
        content_type = request.headers.get("content-type", "")
        wrapper = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii") + body
        message = BytesParser(policy=policy.default).parsebytes(wrapper)
        if not message.is_multipart():
            raise HTTPException(status_code=400, detail="invalid_upload")
        image_bytes = None
        mime = "image/jpeg"
        for part in message.iter_parts():
            field = part.get_param("name", header="content-disposition")
            if field in {"file", "image"}:
                image_bytes = cast(bytes | None, part.get_payload(decode=True))
                mime = part.get_content_type()
                break
        if not image_bytes:
            raise HTTPException(status_code=400, detail="missing_image")
        if not mime.startswith("image/"):
            raise HTTPException(status_code=415, detail="unsupported_image")
        if not settings.gemini_api_key.strip():
            return {"status": "ocr_unavailable", "source": source, "message": "Gemini is not configured. Add the API key or paste the ingredients."}
        extracted = await asyncio.to_thread(gemini.extract_ingredients, image_bytes, mime)
        del image_bytes, body, chunks
        if not extracted:
            return {"status": "ocr_unavailable", "source": source, "message": gemini.ocr_failure_message()}
        if not extracted["found"] or not extracted["ingredients_text"].strip():
            return {"status": "no_ingredients_found", "source": source, "detected_text": "", "message": "No ingredient list was found. Try a clearer image or paste the ingredients."}
        result = await asyncio.to_thread(
            _scan_text,
            extracted["ingredients_text"],
            "camera" if source == "camera" else "upload",
            None,
            "auto",
            extracted["ingredients_text"],
            request=request,
            response=response,
            idempotency_key=idempotency_key,
        )
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Image scan failed")
        return {"status": "ocr_unavailable", "source": source, "message": "We couldn't read this photo. Try a clearer image or paste the ingredients."}


@router.get("/history")
def history_endpoint(
    request: Request,
    response: Response,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=80),
):
    session_id = _session_id(request, response)
    return {"items": history(limit, path=_db_path(), session_id=session_id, offset=offset, search=search), "offset": offset, "limit": limit}


@router.get("/history/{public_id}")
def history_detail(public_id: str, request: Request, response: Response):
    item = get_scan(public_id, session_id=_session_id(request, response), path=_db_path())
    if item is None:
        raise HTTPException(status_code=404, detail="scan_not_found")
    return item


@router.delete("/history/{public_id}")
def history_delete(public_id: str, request: Request, response: Response):
    _check_origin(request)
    deleted = delete_scan(public_id, session_id=_session_id(request, response), path=_db_path())
    if not deleted:
        raise HTTPException(status_code=404, detail="scan_not_found")
    return {"deleted": True, "scan_id": public_id}


@router.delete("/history")
def history_clear(request: Request, response: Response):
    _check_origin(request)
    count = clear_history(session_id=_session_id(request, response), path=_db_path())
    return {"deleted": count}
