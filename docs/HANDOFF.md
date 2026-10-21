# NutriSnap Handoff

## 1. Current Milestone & Step
- Milestone: M0 (Scaffold) & M1 (Parser, Normalizer, Matcher, KB)
- Current Step: Setting up virtual environment (`backend/.venv`) and installing dependencies for M0/M1 test execution and server verification.

## 2. Done (Files & Paths)
- Repo root: `README.md`, `AGENTS.md`, `.github/copilot-instructions.md`, `.gitignore`
- Docs: `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/decisions.md`, `docs/HANDOFF.md`
- Backend Scaffold & Config: `backend/requirements.txt`, `backend/.env.example`, `backend/app/config.py`, `backend/app/schemas.py`, `backend/app/main.py`, `backend/app/api/routes.py`
- M1 Core Modules: `backend/app/core/parser.py`, `backend/app/core/normalizer.py`, `backend/app/core/matcher.py`, `backend/app/core/knowledge_base.py`
- Core Stubs: `backend/app/core/rules.py`, `personalization.py`, `gate.py`, `scoring.py`, `nova_badge.py`, `nutriscore.py`, `language.py`, `ml/base.py`, `hf_nova.py`, `minilm_head.py`
- KB Data & Vocab: `backend/app/data/kb/ingredients.json`, `category_rules.json`, `category_notes.json`, `vocab/common_ingredients.txt`, `golden/golden_products.json`, `nutriscore/nutriscore_2023.json`, `daily_targets.json`
- Spike & Scripts: `backend/notebooks/nova_spike.ipynb`, `backend/scripts/download_model.py`, `eval_golden.py`, `eval_nova_india.py`
- Unit Tests: `backend/tests/conftest.py`, `test_parser.py`, `test_matcher.py`

## 3. Exact Next 3 Steps
1. Finish creating `backend/.venv` (Python 3.13) and install requirements (FastAPI, pydantic, rapidfuzz, pytest, httpx, uvicorn).
2. Run pytest on `backend/tests/` and test `GET /api/health` output + run demo input test script.
3. Git init & commit M0 + M1 milestone work, outputting required M0/M1 reports to user.

## 4. Run Commands & Last Results
- App: `cd backend; .venv\Scripts\uvicorn app.main:app --port 8000` (Pending venv install)
- Tests: `cd backend; .venv\Scripts\pytest -v` (Pending venv install)

## 5. Known Bugs & Half-Finished Files
- None in M0/M1 modules. M2-M6 backend modules are stubs as designed for M0/M1.

## 6. Decisions & Deviations
- Used Python 3.13 for `backend/.venv` (Python 3.14 lacks binary wheels for some PyPI packages).
- `Wheat flour (unspecified)` in `ingredients.json` set to `refined_flour` flag with owner confirmation note.
- KB entries have `explanation`, `swap_tip`, `source` = null and `verified` = false per PRD §15.

## 7. Open Questions
- None blocking M0/M1.
