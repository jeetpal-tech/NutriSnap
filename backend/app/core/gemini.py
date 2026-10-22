"""Optional Google Gemini features. All failures are contained and never affect scoring."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.core.database import DB_PATH, cached_alternatives, cached_ingredient_info, normalize_cache_name, save_alternatives, save_ingredient_info

TIMEOUT_SECONDS = 20.0
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_EXTRACT_SCHEMA = {"type":"OBJECT","properties":{"found":{"type":"BOOLEAN"},"ingredients_text":{"type":"STRING"},"language":{"type":"STRING"},"confidence":{"type":"NUMBER"}},"required":["found","ingredients_text","language","confidence"]}
_INFO_SCHEMA = {"type":"OBJECT","properties":{"items":{"type":"ARRAY","items":{"type":"OBJECT","properties":{"name":{"type":"STRING"},"what_it_is":{"type":"STRING"},"health_note":{"type":"STRING"},"concern_level":{"type":"STRING","enum":["none","low","medium","high"]}},"required":["name","what_it_is","health_note","concern_level"]}}},"required":["items"]}
_ALTERNATIVE_SCHEMA = {"type":"OBJECT","properties":{"alternatives":{"type":"ARRAY","items":{"type":"OBJECT","properties":{"type":{"type":"STRING"},"reason":{"type":"STRING"}},"required":["type","reason"]}}},"required":["alternatives"]}
_FULL_ANALYSIS_SCHEMA = {"type":"OBJECT","properties":{"items":{"type":"ARRAY","items":{"type":"OBJECT","properties":{"name":{"type":"STRING"},"what_it_is":{"type":"STRING"},"health_note":{"type":"STRING"},"risk_level":{"type":"STRING","enum":["low","medium","high"]}},"required":["name","what_it_is","health_note","risk_level"]}},"alternatives":{"type":"ARRAY","items":{"type":"OBJECT","properties":{"type":{"type":"STRING"},"reason":{"type":"STRING"}},"required":["type","reason"]}}},"required":["items","alternatives"]}

def _request_json(prompt: str, schema: dict[str, Any], image_bytes: bytes | None = None, mime: str | None = None) -> dict[str, Any] | None:
    key = settings.gemini_api_key.strip()
    if not key:
        return None
    parts: list[dict[str, Any]] = [{"text": prompt}]
    if image_bytes is not None:
        parts.append({"inlineData": {"mimeType": mime or "image/jpeg", "data": base64.b64encode(image_bytes).decode("ascii")}})
    body = {"contents":[{"role":"user","parts":parts}],"generationConfig":{"responseMimeType":"application/json","responseSchema":schema}}
    url = f"{BASE_URL}/{settings.gemini_model}:generateContent"
    try:
        response = httpx.post(url, headers={"x-goog-api-key": key}, json=body, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        parsed = json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"])
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        # Never log the prompt, OCR text, provider response, or key-bearing URL.
        return None

def extract_ingredients(image_bytes: bytes, mime: str) -> dict[str, Any] | None:
    prompt = ("Copy the printed ingredient list exactly as shown. Never guess missing, blurred, or cut-off words. "
              "Set found=false if no ingredient list is visible. Return only the requested JSON fields.")
    data = _request_json(prompt, _EXTRACT_SCHEMA, image_bytes, mime)
    if not data:
        return None
    try:
        found = bool(data["found"])
        text = data["ingredients_text"] if found else ""
        if not isinstance(text, str) or len(text) > 4000:
            return None
        return {"found": found, "ingredients_text": text, "language": str(data["language"])[:40], "confidence": max(0.0, min(1.0, float(data["confidence"]))), "ai_generated": True}
    except (KeyError, TypeError, ValueError):
        return None

def _owner_info(name: str, kb: Any) -> dict[str, Any] | None:
    if kb is None:
        return None
    norm = normalize_cache_name(name)
    for entry in kb.entries.values():
        all_names = [entry.get("canonical", ""), *entry.get("aliases", [])]
        if norm not in {normalize_cache_name(x) for x in all_names if x}:
            continue
        note = entry.get("explanation")
        if not note:
            return None
        return {"name":name,"what_it_is":entry.get("what_it_is") or entry.get("canonical",name),"health_note":note,
                "concern_level":entry.get("concern_level","none"),"source":"owner","model":None,
                "verified":bool(entry.get("verified")),"ai_generated":False}
    return None

def _list_cache_key(names: list[str]) -> str:
    normalized = sorted(normalize_cache_name(name) for name in names if name.strip())
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False).encode()).hexdigest()

def _database_fallback(names: list[str], fallback_names: list[str], kb: Any, path: Path | str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read owner/SQLite notes only after the full-list Gemini request fails."""
    output: list[dict[str, Any]] = []
    lookup_names = fallback_names if len(fallback_names) == len(names) else names
    try:
        cached = cached_ingredient_info(lookup_names, path)
    except Exception:
        cached = {}
    for requested, lookup in zip(names, lookup_names):
        row = _owner_info(lookup, kb)
        if row is None:
            cached_row = cached.get(normalize_cache_name(lookup))
            if cached_row:
                row = {"name":requested,"what_it_is":cached_row["what_it_is"],"health_note":cached_row["health_note"],
                       "concern_level":cached_row["concern_level"],"risk_level":cached_row["concern_level"],
                       "original_source":cached_row["source"],"model":cached_row["model"],
                       "verified":bool(cached_row["verified"]),"ai_generated":cached_row["source"] == "gemini"}
        if row:
            row = {**row,"name":requested,"source":"database_fallback"}
            risk = row.get("risk_level", row.get("concern_level", "low"))
            row["risk_level"] = risk if risk in {"low", "medium", "high"} else "low"
            row["concern_level"] = row["risk_level"]
            output.append(row)
    alternatives: list[dict[str, Any]] = []
    try:
        cached_alt = cached_alternatives(_list_cache_key(names), path)
        if cached_alt:
            alternatives = json.loads(cached_alt["content_json"])
            alternatives = [{**item,"source":"database_fallback"} for item in alternatives if isinstance(item, dict)]
    except Exception:
        pass
    return output, alternatives

def analyze_ingredient_list(ingredients_text: str, names: list[str], *, fallback_names: list[str] | None = None,
                            kb: Any = None, path: Path | str = DB_PATH) -> dict[str, Any]:
    """Ask Gemini about the complete submitted list first; consult SQLite only on failure."""
    requested = [name.strip() for name in names if name and name.strip()]
    fallback_names = fallback_names or requested
    if requested and settings.gemini_api_key.strip():
        prompt = (
            "Analyze the complete ingredient list below. Identify each listed ingredient and return exactly one item for every "
            "distinct token, preserving its exact token name. For each, provide a short plain-language identification and a "
            "cautious general health note, then set risk_level to low, medium, or high for typical dietary use. Consider that "
            "risk depends on amount, frequency, and individual context; do not call an ingredient toxic without evidence, "
            "do not give medical advice, and do not infer quantities or product facts. Suggest exactly three generic food-type "
            "alternatives that address the ingredient list's overall concerns, with one cautious sentence each and no brand names. "
            "Return empty alternatives only if the input is not a food ingredient list.\n"
            + json.dumps({"ingredients_text": ingredients_text, "ingredient_tokens": requested}, ensure_ascii=False)
        )
        try:
            data = _request_json(prompt, _FULL_ANALYSIS_SCHEMA)
        except Exception:
            data = None
        if data:
            try:
                allowed = {normalize_cache_name(name): name for name in requested}
                generated: dict[str, dict[str, Any]] = {}
                for item in data["items"]:
                    if not isinstance(item, dict):
                        raise ValueError("Invalid Gemini ingredient item")
                    key = normalize_cache_name(str(item.get("name", "")))
                    level = item.get("risk_level")
                    if key not in allowed or key in generated or level not in {"low", "medium", "high"}:
                        raise ValueError("Gemini response did not match ingredient tokens")
                    row = {"name":allowed[key],"what_it_is":" ".join(str(item.get("what_it_is", "")).split()[:20]),
                           "health_note":" ".join(str(item.get("health_note", "")).split()[:40]),"risk_level":level,
                           "concern_level":level,"source":"gemini","model":settings.gemini_model,"verified":False,"ai_generated":True}
                    if not row["what_it_is"] or not row["health_note"]:
                        raise ValueError("Gemini response omitted an explanation")
                    generated[key] = row
                if set(generated) != set(allowed):
                    raise ValueError("Gemini response omitted ingredients")
                raw_alternatives = data["alternatives"]
                if len(raw_alternatives) != 3:
                    raise ValueError("Gemini response must contain three alternatives")
                clean_alternatives = []
                for item in raw_alternatives:
                    if not isinstance(item, dict):
                        raise ValueError("Invalid Gemini alternative")
                    alternative = {"type":" ".join(str(item.get("type", "")).split()[:12]),
                                   "reason":" ".join(str(item.get("reason", "")).split()[:30]),
                                   "ai_generated":True,"source":"gemini"}
                    if not alternative["type"] or not alternative["reason"]:
                        raise ValueError("Gemini response omitted an alternative explanation")
                    clean_alternatives.append(alternative)
                info = list(generated.values())
                try:
                    save_ingredient_info(info, settings.gemini_model, path)
                    save_alternatives(_list_cache_key(requested), clean_alternatives, settings.gemini_model, path)
                except Exception:
                    pass
                return {"ingredient_info":info,"alternatives":clean_alternatives,"source":"gemini"}
            except (KeyError, TypeError, ValueError):
                pass
    info, alternatives = _database_fallback(requested, fallback_names, kb, path)
    return {"ingredient_info":info,"alternatives":alternatives,"source":"database_fallback"}

def ingredient_info(names: list[str], kb: Any = None, path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    requested = list(dict.fromkeys(n.strip() for n in names if n and n.strip()))
    output: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for name in requested:
        owner = _owner_info(name, kb)
        if owner:
            output[normalize_cache_name(name)] = owner
        else:
            missing.append(name)
    try:
        cached = cached_ingredient_info(missing, path)
    except Exception:
        cached = {}
    for name in missing:
        row = cached.get(normalize_cache_name(name))
        if row:
            output[normalize_cache_name(name)] = {"name":name,"what_it_is":row["what_it_is"],"health_note":row["health_note"],
                "concern_level":row["concern_level"],"source":row["source"],"model":row["model"],
                "verified":bool(row["verified"]),"ai_generated":row["source"] == "gemini"}
    need = [n for n in missing if normalize_cache_name(n) not in output]
    if need and settings.gemini_api_key.strip():
        prompt = ("For each ingredient in this JSON array give a neutral identification and a cautious, general health note. "
                  "what_it_is at most 20 words; health_note at most 30 words, hedged, no statistics, citations, or medical advice. "
                  "Do not infer product or serving size. concern_level must be none, low, medium, or high. Retain each exact name. "
                  "Inputs: " + json.dumps(need, ensure_ascii=False))
        data = _request_json(prompt, _INFO_SCHEMA)
        generated: list[dict[str, Any]] = []
        if data:
            allowed = {normalize_cache_name(n):n for n in need}
            for item in data.get("items", []):
                if not isinstance(item, dict):
                    continue
                key = normalize_cache_name(str(item.get("name", "")))
                level = item.get("concern_level")
                if key not in allowed or level not in {"none","low","medium","high"}:
                    continue
                generated.append({"name":allowed[key],"what_it_is":" ".join(str(item.get("what_it_is", "")).split()[:20]),
                    "health_note":" ".join(str(item.get("health_note", "")).split()[:30]),"concern_level":level})
        if generated:
            try:
                save_ingredient_info(generated, settings.gemini_model, path)
            except Exception:
                pass
            for row in generated:
                output[normalize_cache_name(row["name"])] = {**row,"source":"gemini","model":settings.gemini_model,"verified":False,"ai_generated":True}
    return [output[normalize_cache_name(n)] for n in requested if normalize_cache_name(n) in output]

def alternatives(top_flags: list[str], score: int, path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    flags = sorted(set(str(x) for x in top_flags if x))
    cache_key = hashlib.sha256(json.dumps({"flags":flags,"score":int(score)},sort_keys=True).encode()).hexdigest()
    try:
        cached = cached_alternatives(cache_key, path)
        if cached:
            return [{**item,"ai_generated":cached["source"] == "gemini"} for item in json.loads(cached["content_json"])]
    except Exception:
        pass
    if not settings.gemini_api_key.strip():
        return []
    prompt = ("Suggest exactly three generic types of food alternatives that may be a more balanced choice for a food with these flags: "
              + json.dumps(flags) + f". Score context: {int(score)}. No brand names or specific products. Each reason is one cautious sentence, no medical advice or unsupported health claims.")
    data = _request_json(prompt, _ALTERNATIVE_SCHEMA)
    items = data.get("alternatives", []) if data else []
    if len(items) != 3:
        return []
    clean = [{"type":" ".join(str(x.get("type", "")).split()[:12]),"reason":" ".join(str(x.get("reason", "")).split()[:24]),"ai_generated":True} for x in items if isinstance(x,dict)]
    if len(clean) != 3 or any(not x["type"] or not x["reason"] for x in clean):
        return []
    try:
        save_alternatives(cache_key, clean, settings.gemini_model, path)
    except Exception:
        pass
    return clean
