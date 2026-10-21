# NutriSnap

**Packaged food harmfulness detector for Indian consumers.** Paste an ingredient list, get a 0-100 health score, a per-ingredient breakdown, a NOVA processing badge and safer-swap tips. The score is **ML-assisted** (a pretrained NOVA processing-level classifier from Hugging Face) and **automatically falls back to a transparent rule engine** whenever the ML result is unavailable, low-confidence, or inconsistent with the rules.

- Status: academic mini-project, **deadline 2026-10-23**, local-demo scope
- Owner: Jeetpal (B.Tech AI & DS)
- Read next: [`docs/PRD.md`](docs/PRD.md) (what, why, scope, plan) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (how, formulas, API, build order)

---

## What it does

1. User pastes or types an ingredient list (English, Hindi or bilingual with the Hindi feature on).
2. The backend parses and normalizes it (handles `(59%)`, nested brackets, `INS 211` / `E211`, aliases like *maida*, Devanagari text).
3. Each ingredient is matched against a curated knowledge base (exact alias, then fuzzy match).
4. A score is produced:
   - **ML-assisted path:** a pretrained model predicts the product's NOVA group (1-4, processing level). Its probabilities set the base score; ingredient-level rule flags (added sugar, trans fat, preservatives...) adjust it.
   - **Rule-based path (fallback):** the same ingredient flags plus a rule-derived base score.
5. The UI shows the score, band (Low / Moderate / High risk), flagged ingredients, which method produced the score, and why a fallback happened (if it did).

## Three separate signals

| Signal | Measures | Needs | Always shown |
|---|---|---|---|
| NutriSnap score (0-100) | Ingredient flags plus processing level | Ingredient text | Yes |
| NOVA badge (1-4) | Degree of industrial processing | Ingredient text | Yes (can be "unavailable") |
| Nutri-Score grade (A-E) | Nutrient profile per 100 g | Nutrition table from the label | Only when nutrition is entered and the feature is validated and on |

They are never averaged and can disagree (a product with plain ingredients but very high sugar, for example). The UI explains each in one line.

## Automatic fallback (core requirement)

The ML result is used only if **all** of these hold, otherwise the rule-based score is returned and the reason is shown:

| Check | Fallback reason code |
|---|---|
| ML enabled and model loaded | `ml_disabled`, `model_loading`, `model_error` |
| Inference finishes within timeout | `model_timeout` |
| Text has at least 2 Latin-script tokens (unless Hindi is confirmed supported by the model) | `unsupported_language` |
| Top-class probability >= 0.60 (>= 0.80 if the model says NOVA 2) and top-2 margin >= 0.15 | `low_confidence`, `weak_class_uncertain`, `ambiguous_prediction` |
| ML score is not far more reassuring (> 25 pts) or far more alarming (> 45 pts) than the rule score | `ml_rule_disagreement` |

Input that is too short or does not look like food text is rejected before scoring (`insufficient_input`, `not_food_text`). Formulas and defaults: `docs/ARCHITECTURE.md` sections 6-7.

## Features and release plan

| Feature | Release | Flag | Default |
|---|---|---|---|
| Text ingredient analysis, score, band, breakdown | 1 | - | on |
| ML-assisted scoring + automatic rule fallback + method badge | 1 | `ML_ENABLED` | on |
| Scan history (browser localStorage) | 1 | - | on |
| NOVA badge | 1 | `VITE_FEATURE_NOVA_BADGE` | on |
| PDF export (browser print to PDF) | 1 | `VITE_FEATURE_EXPORT` | on |
| Health profile (diabetes / hypertension / high cholesterol), swap tips | 1 if time | - | on |
| Nutrition form + Nutri-Score grade | 2 | `FEATURE_NUTRISCORE`, `VITE_FEATURE_NUTRISCORE` | off until validated |
| Daily cumulative tracker | 2 | `VITE_FEATURE_TRACKER` | off |
| Hindi support (UI, Hindi and bilingual ingredient lists) | 2 | `VITE_FEATURE_HINDI`, `ML_HINDI_SUPPORTED` | off |
| Browser extension (Chrome/Edge) | 2 | - (separate folder) | not loaded by default |
| Re-trained classifier head on Indian products | Stretch | `NOVA_BACKEND` | - |
| Label photo OCR, barcode lookup, product comparison with real products | 3 | - | not built |

Release 1 is the demo target for 2026-10-23. Release 2 features are built in the order listed in `docs/PRD.md` section 10, each behind its flag, and appear in the demo only if they pass their acceptance tests.

## Architecture at a glance

```
React (Vite + Tailwind)  --HTTP/JSON-->  FastAPI
   |  localStorage: history, profile,         |
   |  tracker, language                       |
   |                      language -> parser -> normalizer -> matcher -> knowledge base (JSON)
   |                                          |
   |                     +--------------------+--------------------+
   |                     |                                         |
   |              rule engine (always runs)              ML adapter (HF NOVA model)
   |                     |                                         |
   |                     +--------------> gate / orchestrator <----+
   |                                          |
   |                  score + band + method + reasons + NOVA badge (+ Nutri-Score if enabled)
Chrome/Edge extension (MV3)  ----HTTP/JSON---->  same API
```

## Tech stack

- **Backend:** Python 3.10+, FastAPI, Pydantic v2, rapidfuzz, PyTorch (CPU), transformers, scikit-learn, joblib
- **ML:** `hsilvosa/nova-group-classifier` (Hugging Face, Apache-2.0), with a self-trained fallback head as plan B
- **Frontend:** React, Vite, Tailwind CSS 3.x, React Router, react-i18next, `@fontsource` fonts (Inter, Noto Sans Devanagari)
- **Extension:** plain JavaScript, Manifest V3, no build step
- **Design:** built from the design brief in `docs/ARCHITECTURE.md` section 10.1 (light theme, Tailwind tokens)
- **Not used in Release 1 (not needed, not a hardware limit):** Postgres, Redis, Docker, pgvector, auth, cloud deployment

## Prerequisites

- Python 3.10+ and Node.js 18+
- Chrome or Edge for the extension
- About 600 MB disk for the model

## Quick start

```bash
# 1) Backend
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# 2) Download the pretrained model once (pinned revision, stored in backend/models/)
python scripts/download_model.py

# 3) Run the API (avoid --reload when ML is enabled; it reloads the model on every save)
uvicorn app.main:app --port 8000

# 4) Frontend (new terminal)
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Rules-only development (no model download needed):

```bash
ML_ENABLED=false uvicorn app.main:app --port 8000        # PowerShell: $env:ML_ENABLED="false"; uvicorn app.main:app --port 8000
```

### Browser extension (Release 2)

1. Start the backend and the frontend as above.
2. Open `chrome://extensions` (or `edge://extensions`), enable Developer mode, choose **Load unpacked**, select the `extension/` folder.
3. Select ingredient text on any page, right-click **Analyze selection with NutriSnap**, then click the toolbar icon. Or open the popup and use **Extract from this page**.
4. Defaults: API `http://localhost:8000`, app `http://localhost:5173` (change in the extension's options page).

## Configuration

Backend environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `ML_ENABLED` | `true` | Master switch for the ML path |
| `NOVA_BACKEND` | `hf_hsilvosa` | `hf_hsilvosa` (plan A) or `minilm_head` (plan B) |
| `NOVA_MODEL_DIR` | `backend/models/hsilvosa-nova` | Local model folder |
| `NOVA_MODEL_REVISION` | `f252e3546650954596ff7e5926aab4559c433909` | Pinned HF commit |
| `ML_TIMEOUT_S` | `3.0` | Inference timeout before fallback |
| `ML_MIN_CONFIDENCE` | `0.60` | Gate threshold |
| `ML_NOVA2_MIN_CONFIDENCE` | `0.80` | Stricter threshold when the model predicts NOVA 2 |
| `ML_MIN_MARGIN` | `0.15` | Top-1 minus top-2 probability |
| `ML_MAX_OPTIMISTIC_GAP` | `25` | ML score minus rule score limit |
| `ML_MAX_PESSIMISTIC_GAP` | `45` | Rule score minus ML score limit |
| `ML_HINDI_SUPPORTED` | `false` | Allow Hindi-dominant text into the model (set true only after the spike confirms it works) |
| `FEATURE_NUTRISCORE` | `false` | Enable Nutri-Score computation (only after the validation in the architecture doc passes) |
| `SHOW_UNVERIFIED_BADGE` | `true` | Show "unverified" on KB entries not yet source-checked |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origins |
| `CORS_ORIGIN_REGEX` | empty | Development only, for extensions: `^chrome-extension://.*$` |

Frontend (`frontend/.env`): `VITE_API_URL`, `VITE_FEATURE_NOVA_BADGE`, `VITE_FEATURE_EXPORT`, `VITE_FEATURE_NUTRISCORE`, `VITE_FEATURE_TRACKER`, `VITE_FEATURE_HINDI`.

## API (summary)

- `POST /api/analyze` body `{ "ingredients_text": "...", "profile": {"conditions": ["diabetes"]}, "lang": "en" | "hi", "nutrition": { ... per 100 g ... }, "force_mode": "auto" | "rules" }` (everything except `ingredients_text` is optional)
- `GET /api/health` returns `{ "status": "ok", "ml_status": "ready" | "loading" | "disabled" | "error", "features": { ... } }`

Full schemas and examples: `docs/ARCHITECTURE.md` section 9.

## Tests and evaluation

```bash
cd backend
pytest -q                       # parser, matcher, rules, gate (mocked ML), API contract, Nutri-Score, Hindi
python scripts/eval_golden.py   # hand-labelled golden set: band agreement and method usage
cd ../frontend && npm test      # pure-function tests (tracker math, history cap, prefill)
```

## Project structure

```
nutrisnap/
  README.md
  docs/            PRD.md, ARCHITECTURE.md, decisions.md
  design/refs/     optional reference images for the UI look
  backend/         FastAPI app, KB, rules, ML adapters, tests, scripts
  frontend/        React app
  extension/       Chrome/Edge extension (Release 2)
```

Detailed tree: `docs/ARCHITECTURE.md` section 14.

## Data, models and attribution

- Training/evaluation data: [Open Food Facts](https://world.openfoodfacts.org/), licensed under the **Open Database License (ODbL)**; individual contents under the Database Contents License. Attribution is required: "Contains information from Open Food Facts".
- Model: `hsilvosa/nova-group-classifier` (Apache-2.0). Loaded from a pinned commit because the repo contains a pickled scikit-learn head (`.joblib`); only load pickles from sources and revisions you trust.
- Health content (ingredient explanations, daily limits) must be sourced from FSSAI, ICMR-NIN, WHO or peer-reviewed literature. Entries without a verified source are marked unverified.
- Nutri-Score: computed with the published algorithm; the official logo is not used and the grade is not an Indian standard.

## Limitations and disclaimer

- **Informational only, not medical advice.** Consult a doctor or dietitian for medical decisions.
- NOVA measures **processing level**, which is associated with diet quality; it does not measure toxicity.
- The pretrained model's published accuracy (96.2% top-1) was reported on its own data split, is weakest for NOVA 2 (F1 0.41), and has not been independently validated on Indian packaged foods. This project evaluates it on an Indian subset before trusting it.
- The rule engine scores only ingredients present in the knowledge base. Unknown ingredients are neutral, so scores can be optimistic when KB coverage is low (the UI shows a warning).
- Hindi strings and Hindi ingredient aliases drafted by the coding agent are unreviewed until a fluent reader verifies them.
- The tracker covers only packaged items the user logs, with general (WHO-based) limits, not personal targets.
- The browser extension needs the backend running, does not share history with the web app, and its page extraction is best effort.
- FSSAI's front-of-pack labelling scheme was still being decided in 2026; this project does not implement it.

## Roadmap

1. Release 2 features (Nutri-Score, tracker, Hindi, extension)
2. Re-train the classifier head on an Indian-products subset of Open Food Facts
3. Label photo OCR and barcode lookup
4. Product comparison backed by real product data
5. FSSAI-style warning chips once thresholds are notified
6. Accounts, hosted deployment and cross-device sync
