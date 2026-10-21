# NutriSnap Handoff

## 1. Current Milestone & Step
- Milestone: M2 (Rule Engine, Personalization, Pure ML Combiner) — COMPLETE.
- Current Step: Ready for Milestone M3 (ML Adapters, Gate, Orchestrator /api/analyze).

## 2. Done (Files & Paths)
- Root & Docs: `README.md`, `AGENTS.md`, `.github/copilot-instructions.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/decisions.md`, `docs/HANDOFF.md`
- Core Modules: `backend/app/core/parser.py`, `normalizer.py`, `matcher.py`, `knowledge_base.py`, `rules.py`, `personalization.py`, `scoring.py`
- KB Data: `backend/app/data/kb/ingredients.json` (52 entries, `sodium_bicarbonate` removed), `category_rules.json`, `category_notes.json`, `vocab/common_ingredients.txt`
- Tests: `backend/tests/test_parser.py`, `test_matcher.py`, `test_rules.py` (100/100 passing)
- Demo/Sample Scripts: `backend/scripts/demo_m1.py`, `backend/scripts/sample_scores_m2.py`

## 3. Exact Next 3 Steps
1. M3 Step 1: Implement ML adapters in `backend/app/core/ml/` (`hf_nova.py`, `base.py`).
2. M3 Step 2: Implement fallback gate in `backend/app/core/gate.py` and orchestrator in `backend/app/core/scoring.py`.
3. M3 Step 3: Wire `POST /api/analyze` in `backend/app/api/routes.py` and write fault injection unit tests with mocked model.

## 4. Run Commands & Last Results
- Tests: `cd backend; .venv\Scripts\pytest -v tests` (100 passed in 0.82s)
- Sample scores: `cd backend; .venv\Scripts\python scripts/sample_scores_m2.py` (5 generic products scored)
- Health check: `cd backend; .venv\Scripts\python -c "from fastapi.testclient import TestClient; from app.main import app; ..."` (HTTP 200, 52 KB entries)

## 5. Known Bugs & Half-Finished Files
- None. M0, M1, and M2 are fully tested and functional. M3-M6 modules remain clean stubs.

## 6. Decisions & Deviations
- Removed `sodium_bicarbonate` from `ingredients.json` (not in Appendix A; INS 500(ii) correctly treated as unflagged additive).
- Test assertion adjustment in `test_parser.py`: helper `names()` lowercases for comparing clean names, keeping parser case-preserving and normalizer lowercasing per §5.1-§5.2.
- `combine_ml` in `scoring.py` is a pure function per §6.4; no model inference code in M2.

## 7. Open Questions
- Spike execution: owner to run `backend/notebooks/nova_spike.ipynb` in Colab and record Plan A/B decision in `docs/decisions.md`.
