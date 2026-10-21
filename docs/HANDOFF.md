# NutriSnap Handoff

## 1. Current Milestone & Step
- Milestone: M3a (Fallback Gate, Orchestrator, Background Model Loading, /api/analyze with Mock Model) — COMPLETE.
- Current Step: Ready for Milestone M3b (Real Model Adapter implementation after Colab spike).

## 2. Done (Files & Paths)
- Root & Docs: `README.md`, `AGENTS.md`, `.github/copilot-instructions.md`, `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/decisions.md`, `docs/HANDOFF.md`
- Core Modules:
  - `backend/app/core/parser.py`, `normalizer.py`, `matcher.py`, `knowledge_base.py`
  - `backend/app/core/rules.py` (M2 rule scoring, dedupe, safety caps)
  - `backend/app/core/personalization.py` (profile multipliers)
  - `backend/app/core/gate.py` (M3a checks 0 to 8 in order, check 3a unsupported language, asymmetric disagreement checks at kb_coverage >= 0.60)
  - `backend/app/core/scoring.py` (`combine_ml` pure function + `analyze()` orchestrator lifecycle per ARCHITECTURE §4 & §9.2)
  - `backend/app/core/ml/base.py`, `manager.py` (Protocol, `StubNovaModel`, thread-safe getter/setter, background startup loading)
- API & Routing:
  - `backend/app/main.py` (lifespan loads KB and calls `init_background_model_loader()`)
  - `backend/app/api/routes.py` (`POST /api/analyze` and `GET /api/health` with `ml_status`)
  - `backend/app/schemas.py` (Pydantic v2 schemas for request and response)
- KB Data:
  - `backend/app/data/kb/category_rules.json` (`rule_base.start` set to 80 per M2 leftover tuning)
  - `backend/app/data/kb/ingredients.json` (52 entries), `category_notes.json`, `vocab/common_ingredients.txt`
- Tests:
  - `backend/tests/mocks.py` (`MockNovaModel` configurable per test)
  - `backend/tests/test_parser.py` (36 tests)
  - `backend/tests/test_matcher.py` (33 tests)
  - `backend/tests/test_rules.py` (31 tests, updated dynamically to config)
  - `backend/tests/test_gate_orchestrator.py` (18 tests covering all gate conditions, failures, timeouts, schema)
  - Total: 118/118 passing in 1.78s
- Scripts:
  - `backend/scripts/sample_scores_m2.py` (6 generic products scored)
  - `backend/scripts/demo_m3a_samples.py` (6 M3a test scenarios demonstration)

## 3. Exact Next 3 Steps
1. Owner runs Colab spike (`backend/notebooks/nova_spike.ipynb`) to evaluate Plan A vs Plan B and records decision in `docs/decisions.md`.
2. M3b: Implement real model adapter (`hf_nova.py` or `minilm_head.py`) based on spike outcome.
3. M4a: Frontend scaffold, Tailwind tokens per ARCHITECTURE §10.1, and Scan page (`/`).

## 4. Run Commands & Last Results
- Tests: `cd backend; .venv\Scripts\pytest -v tests` (118 passed in 1.78s)
- Sample scores: `cd backend; .venv\Scripts\python scripts/sample_scores_m2.py` (6 samples scored with `start: 80`)
- M3a demo scenarios: `cd backend; .venv\Scripts\python scripts/demo_m3a_samples.py` (HTTP 200 responses for all 6 scenarios)
- Health check: `curl http://localhost:8000/api/health` -> returns `{"status":"ok","ml_status":"ready",...}`

## 5. Known Bugs & Half-Finished Files
- None. M0 through M3a are fully tested and functional. Real ML adapters (`hf_nova.py`, `minilm_head.py`) remain clean stubs for M3b.

## 6. Decisions & Deviations
- M2 Leftover: Sample 6 ("Potato, Refined palm oil, Salt") initially scored 70 (Low Risk) with `rule_base.start = 85`. Per user instruction, `rule_base.start` was lowered to 80 in `category_rules.json`, moving the sample to 65 (Moderate Risk).
- `test_rules.py` was made strictly dynamic to `kb.rules["rule_base"]["start"]` per ARCHITECTURE §6.
- Background loading in `app/core/ml/manager.py` starts a background thread at startup unless model is a stub or `ML_ENABLED=false`, in which case `ml_status` stays `"disabled"`.
- ML calls run inside a single-worker `ThreadPoolExecutor` with a timeout of `settings.ml_timeout_s`. Any timeout or failure safely falls back to rule-based scoring without returning HTTP 500.

## 7. Open Questions
- Spike execution: owner to run `backend/notebooks/nova_spike.ipynb` in Colab and record Plan A/B decision in `docs/decisions.md`.
