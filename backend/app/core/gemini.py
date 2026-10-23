"""Bounded, typed Gemini provider integration.

Gemini is enrichment/OCR only.  Its result never changes the deterministic
numeric score.  Provider diagnostics stay private while valid partial output
is retained and supplemented item-by-item from verified/local knowledge.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.core.database import (
    DB_PATH,
    cached_alternatives,
    cached_ingredient_info,
    normalize_cache_name,
    save_alternatives,
    save_ingredient_info,
)

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 3
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
PROMPT_VERSION = "full-analysis-v2"

_EXTRACT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "found": {"type": "BOOLEAN"},
        "ingredients_text": {"type": "STRING"},
        "language": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
    },
    "required": ["found", "ingredients_text", "language", "confidence"],
}
_INFO_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "what_it_is": {"type": "STRING"},
                    "health_note": {"type": "STRING"},
                    "concern_level": {"type": "STRING", "enum": ["none", "low", "medium", "high"]},
                },
                "required": ["name", "what_it_is", "health_note", "concern_level"],
            },
        }
    },
    "required": ["items"],
}
_ALTERNATIVE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "alternatives": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"type": {"type": "STRING"}, "reason": {"type": "STRING"}},
                "required": ["type", "reason"],
            },
        }
    },
    "required": ["alternatives"],
}
_FULL_ANALYSIS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "what_it_is": {"type": "STRING"},
                    "health_note": {"type": "STRING"},
                    "risk_level": {"type": "STRING", "enum": ["low", "medium", "high"]},
                },
                "required": ["name", "what_it_is", "health_note", "risk_level"],
            },
        },
        "alternatives": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"type": {"type": "STRING"}, "reason": {"type": "STRING"}},
                "required": ["type", "reason"],
            },
        },
    },
    "required": ["items", "alternatives"],
}


@dataclass(frozen=True)
class GeminiOutcome:
    """Private provider outcome; safe fields only, never raw bodies/prompts."""

    data: dict[str, Any] | None = None
    category: str | None = None
    attempts: int = 0
    status_code: int | None = None
    duration_ms: int = 0
    retry_after_s: float | None = None

    @property
    def ok(self) -> bool:
        return self.data is not None and self.category is None


_client_lock = threading.Lock()
_http_client: httpx.Client | None = None
_last_outcome = GeminiOutcome()
_DEFAULT_HTTPX_POST = httpx.post


def _client() -> httpx.Client:
    global _http_client
    with _client_lock:
        if _http_client is None:
            _http_client = httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0, pool=5.0))
        return _http_client


def close_client() -> None:
    global _http_client
    with _client_lock:
        if _http_client is not None:
            _http_client.close()
            _http_client = None


def _retry_after(response: httpx.Response) -> float | None:
    value = getattr(response, "headers", {}).get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, min(float(value), 10.0))
    except ValueError:
        return None


def _category_for_http(status: int, body: str) -> tuple[str, bool]:
    lowered = body.casefold()
    if status in {401, 403}:
        return "authentication_or_permission", False
    if status == 404:
        return "invalid_model", False
    if status == 429:
        if any(term in lowered for term in ("quota", "exhausted", "daily limit")):
            return "exhausted_quota", False
        return "rate_limit", True
    if status == 400:
        return "invalid_request", False
    if status in {408, 425, 500, 502, 503, 504}:
        return "transient_server_failure", True
    return "provider_http_error", False


def _parse_provider_response(response: httpx.Response) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return None, "malformed_json"
    if not isinstance(payload, dict):
        return None, "malformed_json"
    feedback = payload.get("promptFeedback") or {}
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        return None, "blocked_output"
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None, "no_candidates"
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        return None, "malformed_json"
    finish = str(candidate.get("finishReason", "")).upper()
    if finish in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"}:
        return None, "blocked_output"
    if finish in {"MAX_TOKENS", "RECITATION"}:
        return None, "truncated_output"
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return None, "no_candidates"
    text = next((part.get("text") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)), None)
    if not text:
        return None, "no_candidates"
    try:
        parsed = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return None, "malformed_json"
    if not isinstance(parsed, dict):
        return None, "malformed_json"
    return parsed, None


def _request_json_detailed(
    prompt: str,
    schema: dict[str, Any],
    image_bytes: bytes | None = None,
    mime: str | None = None,
) -> GeminiOutcome:
    """Call Gemini with a deadline and no more than three total attempts."""
    key = settings.gemini_api_key.strip()
    if not key:
        return GeminiOutcome(category="configuration_missing")

    started = time.monotonic()
    deadline = started + max(0.1, float(getattr(settings, "gemini_timeout_s", TIMEOUT_SECONDS)))
    max_attempts = max(1, min(MAX_ATTEMPTS, int(getattr(settings, "gemini_max_attempts", MAX_ATTEMPTS))))
    parts: list[dict[str, Any]] = [{"text": prompt}]
    if image_bytes is not None:
        parts.append(
            {
                "inlineData": {
                    "mimeType": mime or "image/jpeg",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            }
        )
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema},
    }
    url = f"{BASE_URL}/{settings.gemini_model}:generateContent"
    headers = {"x-goog-api-key": key}
    last_category = "provider_error"
    last_status: int | None = None
    retry_after: float | None = None
    attempt = 0

    for attempt in range(1, max_attempts + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return GeminiOutcome(category="deadline_exhausted", attempts=attempt - 1, duration_ms=int((time.monotonic() - started) * 1000))
        timeout = httpx.Timeout(
            max(0.1, min(remaining, 30.0)),
            connect=max(0.1, min(remaining, 5.0)),
            read=max(0.1, min(remaining, 30.0)),
            write=max(0.1, min(remaining, 10.0)),
            pool=max(0.1, min(remaining, 5.0)),
        )
        try:
            # Keep a compatibility seam for tests that patch httpx.post while
            # production uses one managed client across operations.
            if httpx.post is not _DEFAULT_HTTPX_POST:
                response = httpx.post(url, headers=headers, json=body, timeout=timeout)
            else:
                response = _client().post(url, headers=headers, json=body, timeout=timeout)
            response_status = int(getattr(response, "status_code", 200))
            response_text = str(getattr(response, "text", ""))
            last_status = response_status
            if response_status >= 400:
                last_category, retryable = _category_for_http(response_status, response_text[:500])
                retry_after = _retry_after(response)
                if not retryable:
                    break
            else:
                parsed, parse_category = _parse_provider_response(response)
                if parsed is not None:
                    return GeminiOutcome(data=parsed, attempts=attempt, duration_ms=int((time.monotonic() - started) * 1000))
                last_category = parse_category or "schema_failure"
                # Malformed/schema/provider content is not made better by a
                # speculative second request; callers preserve partial data.
                break
        except httpx.TimeoutException:
            last_category = "timeout"
            retryable = True
        except httpx.ConnectError:
            last_category = "connection_failure"
            retryable = True
        except httpx.HTTPError:
            last_category = "connection_failure"
            retryable = True
        except Exception:
            last_category = "provider_error"
            retryable = False

        if attempt >= max_attempts or not retryable:
            break
        remaining = deadline - time.monotonic()
        if retry_after is not None:
            delay = retry_after
        else:
            delay = float(getattr(settings, "gemini_backoff_s", 0.35)) * (2 ** (attempt - 1))
            delay += random.uniform(0.0, 0.15)
        delay = min(max(0.0, delay), max(0.0, remaining - 0.05))
        if delay > 0:
            time.sleep(delay)

    return GeminiOutcome(
        category=last_category,
        attempts=min(max_attempts, attempt),
        status_code=last_status,
        retry_after_s=retry_after,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _request_json(prompt: str, schema: dict[str, Any], image_bytes: bytes | None = None, mime: str | None = None) -> dict[str, Any] | None:
    """Backward-compatible data-only wrapper; detailed outcome stays private."""
    global _last_outcome
    _last_outcome = _request_json_detailed(prompt, schema, image_bytes, mime)
    return _last_outcome.data


def _compact(value: Any, words: int) -> str:
    return " ".join(str(value or "").split()[:words])


def _name_key(value: str) -> str:
    value = normalize_cache_name(value)
    value = re.sub(r"[^\w\u0900-\u097f]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _dedupe_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for name in names:
        clean = " ".join(str(name).split())
        key = _name_key(clean)
        if clean and key not in seen:
            seen.add(key)
            output.append(clean)
    return output


def extract_ingredients(image_bytes: bytes, mime: str) -> dict[str, Any] | None:
    prompt = (
        "Inspect the whole package image and find the section headed 'Ingredients' or equivalent, including text wrapped around a can or bottle. "
        "Ignore nutrition facts, branding, barcode, and recycling text. Transcribe the ingredient section in order, preserving parentheses and INS/E numbers. "
        "Do not invent words: mark an unreadable span as [unclear]. Set found=false only when no ingredient section is visible. "
        "Return only the requested JSON fields."
    )
    data = _request_json(prompt, _EXTRACT_SCHEMA, image_bytes, mime)
    if not data:
        return None
    try:
        found = bool(data["found"])
        text = data["ingredients_text"] if found else ""
        if not isinstance(text, str) or len(text) > 4000:
            return None
        return {
            "found": found,
            "ingredients_text": text,
            "language": str(data["language"])[:40],
            "confidence": max(0.0, min(1.0, float(data["confidence"]))),
            "ai_generated": True,
        }
    except (KeyError, TypeError, ValueError):
        return None


def ocr_failure_message() -> str:
    """Return a short user-facing OCR failure without exposing provider details."""
    category = _last_outcome.category
    if category == "exhausted_quota":
        return "Gemini has reached its current usage quota. Try again after the quota resets, or paste the ingredient text."
    if category == "rate_limit":
        return "Gemini is receiving too many requests right now. Wait a moment and try again, or paste the ingredient text."
    if category == "authentication_or_permission":
        return "Gemini rejected the configured API key. Check the key and its API access, or paste the ingredient text."
    if category == "invalid_model":
        return "The configured Gemini model is unavailable. Check the model setting, or paste the ingredient text."
    return "We couldn't read the ingredient panel in this photo. Try a closer, sharper image or paste the ingredients."


def _owner_info(name: str, kb: Any) -> dict[str, Any] | None:
    if kb is None:
        return None
    norm = _name_key(name)
    for entry in kb.entries.values():
        all_names = [entry.get("canonical", ""), *entry.get("aliases", [])]
        if norm not in {_name_key(x) for x in all_names if x}:
            continue
        note = entry.get("explanation")
        if not note or not entry.get("verified"):
            return None
        return {
            "name": name,
            "what_it_is": entry.get("what_it_is") or entry.get("canonical", name),
            "health_note": note,
            "concern_level": entry.get("concern_level", "none"),
            "source": "owner",
            "model": None,
            "verified": True,
            "ai_generated": False,
        }
    return None


def _list_cache_key(names: list[str]) -> str:
    normalized = sorted(_name_key(name) for name in names if str(name).strip())
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False).encode()).hexdigest()


def _unknown_item(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "what_it_is": None,
        "health_note": None,
        "risk_level": "unknown",
        "concern_level": "unknown",
        "source": "unavailable",
        "model": None,
        "verified": False,
        "ai_generated": False,
    }


def _database_fallback(
    names: list[str],
    fallback_names: list[str],
    kb: Any,
    path: Path | str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Use verified knowledge, then versioned cache, then explicit unknown."""
    output: list[dict[str, Any]] = []
    lookup_names = fallback_names if len(fallback_names) == len(names) else names
    try:
        cached = cached_ingredient_info(lookup_names, path, model=settings.gemini_model, prompt_version=PROMPT_VERSION)
    except Exception:
        cached = {}
    for requested, lookup in zip(names, lookup_names):
        row = _owner_info(lookup, kb)
        if row is None:
            cached_row = cached.get(normalize_cache_name(lookup))
            if cached_row:
                row = {
                    "name": requested,
                    "what_it_is": cached_row["what_it_is"],
                    "health_note": cached_row["health_note"],
                    "concern_level": cached_row["concern_level"],
                    "risk_level": cached_row["concern_level"],
                    "source": "database_fallback",
                    "model": cached_row["model"],
                    "verified": bool(cached_row["verified"]),
                    "ai_generated": cached_row["source"] == "gemini",
                }
        output.append({**(_unknown_item(requested) if row is None else row), "name": requested})

    alternatives: list[dict[str, Any]] = []
    try:
        cached_alt = cached_alternatives(
            _list_cache_key(names), path, model=settings.gemini_model, prompt_version=PROMPT_VERSION
        )
        if cached_alt:
            raw = json.loads(cached_alt["content_json"])
            if isinstance(raw, list):
                alternatives = [
                    {**item, "source": "database_fallback"}
                    for item in raw[:3]
                    if isinstance(item, dict) and item.get("type") and item.get("reason")
                ]
    except Exception:
        logger.warning("Gemini fallback cache read failed", exc_info=True)
    return output, alternatives


def _clean_alternatives(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    clean: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        alternative = {"type": _compact(item.get("type"), 12), "reason": _compact(item.get("reason"), 30)}
        if alternative["type"] and alternative["reason"]:
            clean.append(alternative)
        if len(clean) == 3:
            break
    return clean


def _ingredient_alternatives(names: list[str]) -> list[dict[str, Any]]:
    """Offer cautious, generic comparisons based only on the submitted text."""
    text = " ".join(names).casefold()
    suggestions: list[dict[str, Any]] = []
    if re.search(r"\b(sugar|syrup|honey|dextrose|fructose|maltose|sweetener|sucralose|aspartame)\b", text):
        suggestions.append({"type": "Unsweetened or lower-sugar option", "reason": "Compare similar products for less added sugar per serving."})
    if re.search(r"\b(salt|sodium|brine|benzoate)\b", text):
        suggestions.append({"type": "Lower-sodium option", "reason": "Compare the sodium amount per serving on similar products."})
    if re.search(r"\b(palm oil|palmolein|hydrogenated|vanaspati|shortening|vegetable fat)\b", text):
        suggestions.append({"type": "Option with less saturated fat", "reason": "Compare saturated fat on the nutrition panels of similar products."})
    if re.search(r"\b(carbonated water|carbon dioxide|caffeine|cola|caramel colour|caramel color)\b", text):
        suggestions.append({"type": "Unsweetened water or sparkling water", "reason": "A simple drink option to compare with sweetened or flavoured beverages."})
    if not suggestions:
        suggestions.append({"type": "A similar option with a shorter ingredient list", "reason": "Compare labels and choose the option that best fits your needs."})
    return [{**item, "ai_generated": False, "source": "general_guidance"} for item in suggestions[:3]]


def analyze_ingredient_list(
    ingredients_text: str,
    names: list[str],
    *,
    fallback_names: list[str] | None = None,
    kb: Any = None,
    path: Path | str = DB_PATH,
) -> dict[str, Any]:
    """Attempt live full-list Gemini first, preserving valid partial results."""
    requested = _dedupe_names(names)
    fallback_names = fallback_names or requested
    generated: dict[str, dict[str, Any]] = {}
    generated_alternatives: list[dict[str, Any]] = []
    outcome = GeminiOutcome(category="configuration_missing")

    if requested and settings.gemini_api_key.strip():
        prompt = (
            "Analyze the complete ingredient list below. Return one item for each distinct token that can be safely associated "
            "with the provided token list; preserve the token name when possible. For each, provide a short plain-language "
            "identification and a cautious general health note, then set risk_level to low, medium, or high for typical dietary "
            "use. Consider amount, frequency, and individual context; do not give medical advice or infer quantities. Suggest up "
            "to three generic food-type alternatives, never brands. Unknown or uncertain items must be omitted rather than guessed.\n"
            + json.dumps({"ingredients_text": ingredients_text, "ingredient_tokens": requested}, ensure_ascii=False)
        )
        data = _request_json(prompt, _FULL_ANALYSIS_SCHEMA)
        outcome = _last_outcome if _last_outcome.data is data else GeminiOutcome(data=data, attempts=1)
        if data:
            allowed = {_name_key(name): name for name in requested}
            raw_items = data.get("items", [])
            if not isinstance(raw_items, list) or not isinstance(data.get("alternatives"), list):
                outcome = GeminiOutcome(
                    data=data,
                    category="schema_failure",
                    attempts=outcome.attempts,
                    status_code=outcome.status_code,
                    duration_ms=outcome.duration_ms,
                )
            if isinstance(raw_items, list):
                for item in raw_items:
                    if not isinstance(item, dict):
                        continue
                    key = _name_key(str(item.get("name", "")))
                    level = item.get("risk_level")
                    what = _compact(item.get("what_it_is"), 20)
                    note = _compact(item.get("health_note"), 40)
                    if key not in allowed or key in generated or level not in {"low", "medium", "high"} or not what or not note:
                        continue
                    generated[key] = {
                        "name": allowed[key],
                        "what_it_is": what,
                        "health_note": note,
                        "risk_level": level,
                        "concern_level": level,
                        "source": "gemini",
                        "model": settings.gemini_model,
                        "verified": False,
                        "ai_generated": True,
                    }
            generated_alternatives = [
                {**item, "ai_generated": True, "source": "gemini"}
                for item in _clean_alternatives(data.get("alternatives"))
            ]

            try:
                if generated:
                    save_ingredient_info(
                        list(generated.values()),
                        settings.gemini_model,
                        path,
                        prompt_version=PROMPT_VERSION,
                        ttl_seconds=settings.gemini_cache_ttl_s,
                    )
                if generated_alternatives:
                    save_alternatives(
                        _list_cache_key(requested),
                        generated_alternatives,
                        settings.gemini_model,
                        path,
                        prompt_version=PROMPT_VERSION,
                        ttl_seconds=settings.gemini_cache_ttl_s,
                    )
            except Exception:
                # A cache write must not erase a valid live provider result.
                logger.warning("Gemini cache write failed", exc_info=True)

    missing = [name for name in requested if _name_key(name) not in generated]
    fallback_info, fallback_alternatives = _database_fallback(
        missing,
        [fallback_names[names.index(name)] if name in names and names.index(name) < len(fallback_names) else name for name in missing],
        kb,
        path,
    ) if missing else ([], [])
    info_by_key = {**{key: value for key, value in generated.items()}, **{_name_key(row["name"]): row for row in fallback_info}}
    info = [info_by_key[_name_key(name)] for name in requested if _name_key(name) in info_by_key]
    alternatives = generated_alternatives or fallback_alternatives or _ingredient_alternatives(names)
    has_supported_fallback = any(
        item.get("source") in {"database_fallback", "owner"} and item.get("risk_level", item.get("concern_level")) != "unknown"
        for item in fallback_info
    ) or bool(fallback_alternatives)
    if generated and missing:
        source = "mixed"
    elif generated:
        source = "gemini"
    elif has_supported_fallback:
        source = "database_fallback"
    else:
        source = "unavailable"
    return {
        "ingredient_info": info,
        "alternatives": alternatives,
        "source": source,
        "provider_category": outcome.category,
        "provider_attempts": outcome.attempts,
        "provider_status_code": outcome.status_code,
        "provider_duration_ms": outcome.duration_ms,
    }


def ingredient_info(names: list[str], kb: Any = None, path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    """Legacy single-item helper used by local tools; cache-first by design."""
    requested = _dedupe_names(names)
    output: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for name in requested:
        owner = _owner_info(name, kb)
        if owner:
            output[_name_key(name)] = owner
        else:
            missing.append(name)
    try:
        cached = cached_ingredient_info(missing, path, model=settings.gemini_model, prompt_version="single-item-v2")
    except Exception:
        cached = {}
    for name in missing:
        row = cached.get(normalize_cache_name(name))
        if row:
            output[_name_key(name)] = {
                "name": name,
                "what_it_is": row["what_it_is"],
                "health_note": row["health_note"],
                "concern_level": row["concern_level"],
                "source": row["source"],
                "model": row["model"],
                "verified": bool(row["verified"]),
                "ai_generated": row["source"] == "gemini",
            }
    need = [n for n in missing if _name_key(n) not in output]
    if need and settings.gemini_api_key.strip():
        prompt = (
            "For each ingredient in this JSON array give a neutral identification and a cautious, general health note. "
            "what_it_is at most 20 words; health_note at most 30 words, hedged, no medical advice. concern_level must be none, low, medium, or high. Retain each exact name. Inputs: "
            + json.dumps(need, ensure_ascii=False)
        )
        data = _request_json(prompt, _INFO_SCHEMA)
        generated: list[dict[str, Any]] = []
        if data:
            allowed = {_name_key(n): n for n in need}
            for item in data.get("items", []) if isinstance(data.get("items"), list) else []:
                if not isinstance(item, dict):
                    continue
                key = _name_key(str(item.get("name", "")))
                level = item.get("concern_level")
                what = _compact(item.get("what_it_is"), 20)
                note = _compact(item.get("health_note"), 30)
                if key in allowed and level in {"none", "low", "medium", "high"} and what and note:
                    generated.append({"name": allowed[key], "what_it_is": what, "health_note": note, "concern_level": level})
        if generated:
            try:
                save_ingredient_info(generated, settings.gemini_model, path, prompt_version="single-item-v2", ttl_seconds=settings.gemini_cache_ttl_s)
            except Exception:
                logger.warning("Gemini single-item cache write failed", exc_info=True)
            for row in generated:
                output[_name_key(row["name"])] = {**row, "source": "gemini", "model": settings.gemini_model, "verified": False, "ai_generated": True}
    return [output[_name_key(n)] for n in requested if _name_key(n) in output]


def alternatives(top_flags: list[str], score: int, path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    flags = sorted(set(str(x) for x in top_flags if x))
    cache_key = hashlib.sha256(json.dumps({"flags": flags, "score": int(score)}, sort_keys=True).encode()).hexdigest()
    try:
        cached = cached_alternatives(cache_key, path, model=settings.gemini_model, prompt_version="alternatives-v2")
        if cached:
            return [{**item, "ai_generated": cached["source"] == "gemini"} for item in json.loads(cached["content_json"]) if isinstance(item, dict)]
    except Exception:
        logger.warning("Gemini alternatives cache read failed", exc_info=True)
    if not settings.gemini_api_key.strip():
        return []
    prompt = (
        "Suggest up to three generic types of food alternatives that may be a more balanced choice for a food with these flags: "
        + json.dumps(flags)
        + f". Score context: {int(score)}. No brands or products. Each reason is one cautious sentence, no medical advice."
    )
    data = _request_json(prompt, _ALTERNATIVE_SCHEMA)
    clean = _clean_alternatives(data.get("alternatives") if data else [])
    if not clean:
        return []
    try:
        save_alternatives(cache_key, clean, settings.gemini_model, path, prompt_version="alternatives-v2", ttl_seconds=settings.gemini_cache_ttl_s)
    except Exception:
        logger.warning("Gemini alternatives cache write failed", exc_info=True)
    return [{**item, "ai_generated": True} for item in clean]
