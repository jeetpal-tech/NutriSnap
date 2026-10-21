"""
demo_m1.py - Milestone M1 demonstration script.
Parses, normalizes, and matches the demo input per user request:
"Refined wheat flour (maida) (61%), Sugar, Palm oil, Salt, Raising agents [INS 500(ii)], Flavour enhancer (INS 621), Palm olien"
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.parser import parse
from app.core.normalizer import normalize
from app.core.matcher import match_tokens
from app.core.knowledge_base import KnowledgeBase

DEMO_INPUT = (
    "Refined wheat flour (maida) (61%), Sugar, Palm oil, Salt, "
    "Raising agents [INS 500(ii)], Flavour enhancer (INS 621), Palm olien"
)

def run():
    kb = KnowledgeBase()
    kb.load()

    tokens = parse(DEMO_INPUT)
    print("=== INPUT TEXT ===")
    print(DEMO_INPUT)
    print("\n=== PARSER OUTPUT ===")
    for t in tokens:
        print(f"[{t.position}] raw: {t.raw!r}")
        print(f"    name: {t.name!r}, sub_text: {t.sub_text!r}, percent: {t.percent}, ins_codes: {t.ins_codes}")

    norm_tokens = [normalize(t) for t in tokens]
    positions = [t.position for t in tokens]
    results, coverage = match_tokens(norm_tokens, positions, kb)

    print(f"\n=== MATCHER OUTPUT (kb_coverage: {coverage:.2%}) ===")
    for r in results:
        print(f"[{r.position}] matched: {r.matched}")
        print(f"    kb_id: {r.kb_id}, canonical: {r.canonical!r}, flag: {r.flag}")
        print(f"    method: {r.match_method}, fuzzy_score: {r.fuzzy_score}")

if __name__ == "__main__":
    run()
