"""Evaluate the current rules-only scorer on owner-supplied golden products."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.knowledge_base import KnowledgeBase
from app.core.scoring import analyze

GOLDEN_PATH = Path(__file__).parent.parent / "app" / "data" / "golden" / "golden_products.json"

def main() -> None:
    products = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if not products:
        print("Golden set is empty. Add only ingredient lists copied from real packs; none were invented.")
        return
    kb = KnowledgeBase()
    kb.load()
    scored = []
    for product in products:
        name = product.get("name", "Unnamed product")
        expected = product.get("expected_band")
        try:
            result = analyze(product["ingredients_text"], force_mode="auto", kb=kb)
        except (KeyError, ValueError) as exc:
            print(f"SKIP {name}: {exc}")
            continue
        if result.status != "ok":
            print(f"SKIP {name}: {result.status}")
            continue
        match = result.band == expected if expected else None
        scored.append((match, result))
        print(f"{name}: {result.score:>3} {result.band}; method={result.scoring_method}; expected={expected or 'not set'}; match={match if match is not None else 'n/a'}")
    known = [match for match, _ in scored if match is not None]
    agreement = sum(known) / len(known) if known else None
    print(f"\nScored {len(scored)}/{len(products)} products; expected-band agreement: {agreement:.0%}" if agreement is not None else f"\nScored {len(scored)}/{len(products)} products; no expected bands supplied.")
    print("Runtime is rules-only; ML comparison metrics are intentionally unavailable.")

if __name__ == "__main__":
    main()
