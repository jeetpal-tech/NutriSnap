# NutriSnap Handoff

## 1. Current Milestone & Step
- Milestone: M0 (Scaffold) & M1 (Parser, Normalizer, Matcher, KB) — COMPLETE. Ready for M2.
- Current Step: Milestone M0 & M1 review and presentation of outputs.

## 2. Done (Files & Paths)
- Root & Config: `README.md`, `AGENTS.md`, `.github/copilot-instructions.md`, `.gitignore`, `backend/requirements.txt`, `backend/.env.example`
- Docs: `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/decisions.md`, `docs/HANDOFF.md`
- Backend Core: `backend/app/config.py`, `backend/app/schemas.py`, `backend/app/main.py`, `backend/app/api/routes.py`
- M1 Modules: `backend/app/core/parser.py`, `backend/app/core/normalizer.py`, `backend/app/core/matcher.py`, `backend/app/core/knowledge_base.py`
- Stubs (M2-M10): `rules.py`, `personalization.py`, `gate.py`, `scoring.py`, `nova_badge.py`, `nutriscore.py`, `language.py`, `ml/base.py`, `hf_nova.py`, `minilm_head.py`
- Data & KB: `backend/app/data/kb/ingredients.json` (53 entries), `category_rules.json`, `category_notes.json`, `vocab/common_ingredients.txt`, `golden/golden_products.json`, `nutriscore/nutriscore_2023.json`, `daily_targets.json`
- Notebooks & Scripts: `backend/notebooks/nova_spike.ipynb`, `backend/scripts/download_model.py`, `eval_golden.py`, `eval_nova_india.py`, `backend/scripts/demo_m1.py`
- Tests: `backend/tests/conftest.py`, `test_parser.py`, `test_matcher.py` (69/69 passing)

## 3. Exact Next 3 Steps
1. M2: Implement `rules.py`, `personalization.py` (penalties, dedupe, position multipliers, sugar splitting, bonus, caps).
2. Write unit tests for rules, personalization, and safety caps per ARCHITECTURE §6.2-§6.5.
3. Test 5 sample product ingredient lists and commit M2.

## 4. Run Commands & Last Results
- App server: `cd backend; .venv\Scripts\uvicorn app.main:app --port 8000`
- GET /api/health: HTTP 200 `{"status":"ok","ml_status":"disabled","backend":"hf_hsilvosa","kb_version":1,"kb_entries":53,"features":{"nutriscore":false,"hindi_ml":false}}`
- Tests: `cd backend; .venv\Scripts\pytest -v tests` (69 passed in 0.75s)
- Demo script: `cd backend; .venv\Scripts\python scripts/demo_m1.py` (100% coverage on demo input)

## 5. Known Bugs & Half-Finished Files
- None. M0 and M1 fully verified.

## 6. Decisions & Deviations
- Used Python 3.13 for `backend/.venv` due to broad package compatibility on Windows.
- Configured git user `jeetpal <jeetpal7067@gmail.com>` with origin remote `https://github.com/jeetpal-tech/NutriSnap.git`.
- KB entries have `explanation`, `swap_tip`, `source` = null and `verified` = false per PRD §15.

## 7. Open Questions
- None blocking M2.
