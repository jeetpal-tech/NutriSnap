"""
sample_scores_m2.py - Generate 6 sample scores with penalty breakdown tables (Milestone M2).

Products tested (generic, no brand names):
1. Instant-noodle-like
2. Biscuit-like
3. Plain oats
4. Chips-like
5. Whole wheat atta
6. Plain salted chips (Potato, Refined palm oil, Salt)
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.parser import parse
from app.core.normalizer import normalize
from app.core.matcher import match_tokens
from app.core.rules import calculate_rule_score
from app.core.knowledge_base import KnowledgeBase

SAMPLES = [
    {
        "category": "Instant-noodle-like",
        "text": "Refined wheat flour, Palm oil, Salt, Wheat gluten, Flavour enhancer (INS 621), Flavour enhancer (INS 627), Flavour enhancer (INS 631), Hydrolysed vegetable protein, Sugar",
    },
    {
        "category": "Biscuit-like",
        "text": "Refined wheat flour (maida) (53%), Sugar, Palm oil, Invert sugar syrup, Raising agents [INS 500(ii)], Emulsifier (INS 471), Artificial flavour",
    },
    {
        "category": "Plain oats",
        "text": "Rolled oats (100%)",
    },
    {
        "category": "Chips-like",
        "text": "Potato, Refined palm oil, Sugar, Salt, Flavour enhancer (INS 621), Maltodextrin, TBHQ (INS 319)",
    },
    {
        "category": "Whole wheat atta",
        "text": "Whole wheat flour (100%)",
    },
    {
        "category": "Potato, Refined palm oil, Salt",
        "text": "Potato, Refined palm oil, Salt",
    },
]

def run():
    kb = KnowledgeBase()
    kb.load()

    for item in SAMPLES:
        cat = item["category"]
        text = item["text"]
        tokens = parse(text)
        norm_tokens = [normalize(t) for t in tokens]
        positions = [t.position for t in tokens]
        matches, coverage = match_tokens(norm_tokens, positions, kb)
        res = calculate_rule_score(matches, tokens, kb.rules)

        print("=" * 80)
        print(f"Product: {cat}")
        print(f"Ingredients: {text}")
        print(f"Coverage: {coverage:.1%} | Score: {res.score}/100 ({res.band})")
        print(f"Base: {res.base} (Complexity: -{res.complexity_penalty}, Unflagged Additives: -{res.unflagged_additive_penalty})")
        print(f"Penalty: {res.penalty} (Capped: {res.penalty < res.penalty_before_cap}) | Bonus: {res.bonus}")
        if res.caps_applied:
            print(f"Safety Caps Applied: {res.caps_applied}")
        print("-" * 80)
        print(f"{'Pos':>3}  {'Ingredient':<28} {'Flag':<25} {'Points':>7}")
        print("-" * 80)
        for ing in res.scored_ingredients:
            status = ing.flag or ("(unmatched)" if not ing.matched else "(neutral)")
            if ing.deduplicated:
                status += " [deduped]"
            print(f"{ing.position:>3}  {ing.name[:28]:<28} {status:<25} {ing.points:>+7.1f}")
        if res.sugar_splitting_applied:
            print(f"     {'[Sugar Splitting Extra Penalty]':<54} {-4.0:>+7.1f}")
        print("=" * 80)
        print()

if __name__ == "__main__":
    run()
