# NutriSnap Handoff

## Goal

Deliver a shopper-facing NutriSnap app with a professional neo-brutalist UI, no public database/schema/debug screens, Gemini-first enrichment with bounded fallback, and durable recording of accepted scans. The user explicitly deferred the broader security/ownership work in section 7 of `docs/CODEX_FULLSTACK_FIX_PROMPT.md`; do not expand that scope in the next pass unless requested.

## Current state

- Frontend repair is implemented: customer navigation is Scan + History only; `/database` redirects to Scan; database/SQL/query/provider-internal copy is removed from the UI; Camera/Upload/Paste flows, OCR review, results, history, empty/loading/error states, and neo-brutalist tokens/components are in place.
- Backend repair is implemented: Gemini calls use a managed client, typed failure categories, a bounded retry/deadline policy, partial-result retention, item-level unknown states, versioned cache freshness, and fallback without changing the deterministic score.
- Scan persistence is implemented with a SQLite lifecycle (`received`/`analyzing`/`completed`/`completed_limited`/`failed`/`interrupted`), opaque public IDs, idempotency keys, result snapshots, ingredient children, provider-attempt records, and restart reconciliation. Existing SQLite is intentionally retained for the single-node demo; PostgreSQL was not introduced.
- Internal `/api/stats` and `/api/queries` routes are removed. API docs are disabled by default. The professor-facing schema/query material remains in docs and local scripts only.
- A migration defect was found during live smoke testing: an old database had `provider_attempt` referencing a deleted `scan_legacy` table. `initialize()` now repairs that foreign key in place while preserving rows.
- Public result projection now removes provider model/cache metadata from ingredient enrichment. The customer UI still labels AI-generated notes and unknown items without exposing internal fallback names.
- The `?ingredients=...&autorun=1` deep link now automatically runs a pasted-text check, which keeps the existing extension/deep-link contract usable.

## Gemini verification and limit

- A real configured Gemini request was attempted during local smoke testing on October 22, 2026. Google returned HTTP 429/exhausted-quota behavior. NutriSnap did not fail the scan: it recorded the provider outcome and returned a limited result using stored fallback notes/unknown state.
- This proves the failure path and fallback path, not healthy live Gemini success. Do not claim the provider is reliable until the owner checks quota/key/model availability and repeats a bounded smoke test.
- Current configured model remains the existing environment choice. No key or secret is stored in this handoff.

## Run

From the project root, use the existing setup in README.md, then launch with `run_dev.bat`. The verified local endpoints were `http://localhost:5173` and `http://localhost:8000`.

## Checks completed

- Backend tests: `backend/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider backend/tests` -> **139 passed, 1 skipped, 1 Starlette/httpx deprecation warning**.
- Targeted hardening/Gemini tests -> **14 passed, 1 warning**.
- Python compilation: `backend/.venv/Scripts/python.exe -m compileall -q backend/app backend/tests` -> passed.
- Frontend build: `npm --prefix frontend run build` -> passed; Vite transformed 1,585 modules.
- Database scripts: `backend/.venv/Scripts/python.exe scripts/init_db.py` -> passed; `demo_queries.py` -> passed; `eval_golden.py` -> completed with the intentionally empty golden set, so accuracy evaluation remains **not performed**.
- Browser smoke: localhost Scan rendered without initial camera permission; `?ingredients=...&autorun=1` reached Results; Results displayed unknown ingredients as “not assessed”; History rendered the saved check; direct `/database` no longer showed database content; mobile viewport around 310 px had no horizontal scrollbar after the responsive fix. Exact 360 px and 1280 px screenshot checks remain to be done by the owner/browser.
- Live API checks: `/api/health` returned 200; fresh `/docs` and `/api/stats` returned 404; `/api/analyze` returned a persisted `completed_limited` result after the provider quota failure.

## Changed files

- `backend/app/core/gemini.py`: bounded provider integration, typed outcomes, retries, partial validation, cache version/TTL use.
- `backend/app/core/database.py`: lifecycle/idempotency/cache/provider-attempt persistence, migrations, legacy FK repair, local query helpers retained.
- `backend/app/api/routes.py`, `backend/app/main.py`, `backend/app/config.py`, `backend/app/schemas.py`: public endpoint projection, lifecycle orchestration, docs gating, stable paths, response metadata.
- `backend/tests/conftest.py`, `backend/tests/test_gemini.py`, `backend/tests/test_backend_hardening.py`: deterministic provider, migration, lifecycle, route, and privacy-projection checks.
- `frontend/src/App.jsx`, `frontend/src/style.css`, `frontend/tailwind.config.js`, `frontend/src/components/`, `frontend/src/pages/`, `frontend/src/lib/`: neo-brutalist customer flow and database/debug removal.
- `docs/CODEX_FULLSTACK_FIX_PROMPT.md`: full repair specification supplied by the user.

## Remaining gaps

1. Healthy live Gemini success is blocked by the observed 429/quota response; owner action is to verify the key’s quota/model access and rerun the bounded smoke test.
2. MiniLM/NumPy runtime validation remains incomplete; one existing test is skipped when the local model dependency/artifacts are unavailable.
3. Golden-product evaluation remains **not performed** because the owner-supplied golden set is empty. Do not invent branded examples.
4. Exact 360 px and 1280 px visual checks, real readable label-image OCR, and a full browser test suite are still outstanding.
5. The user deferred the broader section-7 security/ownership work. Existing changes in the current checkout include session-cookie scaffolding from the earlier interrupted work; do not add more security scope without instruction.
6. npm audit advisories were previously reported and were not blindly upgraded during this repair.

## Next concrete step

Owner should verify Gemini quota/key/model access, then run one pasted scan and one readable label-image scan through `run_dev.bat`. If live Gemini succeeds, inspect that the response is `ingredient_analysis_source`-appropriate, the scan appears in History, and the SQLite `provider_attempt` row records the successful outcome. After that, perform the exact 360/1280 browser review and fill the golden set with real owner-supplied labels.
