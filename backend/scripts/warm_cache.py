"""Pre-generate Gemini summaries for known ingredients and supplied golden labels."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.core.gemini import ingredient_info
from app.core.knowledge_base import KnowledgeBase
from app.core.parser import parse


def main() -> int:
    if not settings.gemini_api_key.strip():
        print("GEMINI_API_KEY is not configured; no network requests were made.")
        return 1

    kb = KnowledgeBase()
    kb.load()
    names = {entry.get("canonical", "").strip() for entry in kb.entries.values()}
    golden_path = Path(__file__).parents[1] / "app" / "data" / "golden" / "golden_products.json"
    products = json.loads(golden_path.read_text(encoding="utf-8"))
    for product in products:
        names.update(token.name.strip() for token in parse(product.get("ingredients_text", "")))
    names.discard("")

    generated = 0
    for start in range(0, len(names), 8):
        batch = sorted(names)[start:start + 8]
        rows = ingredient_info(batch, kb=kb)
        generated += sum(row.get("ai_generated", False) for row in rows)
        print(f"Processed {min(start + len(batch), len(names))}/{len(names)} ingredient names")
    print(f"Warm-cache finished: {generated} Gemini summaries available; owner KB notes take priority.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
