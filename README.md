# NutriSnap

NutriSnap reviews packaged-food ingredient labels. It combines a transparent ingredient-rule score with NOVA processing information, optional Gemini label reading and ingredient explanations, and a local SQLite history. It is a demo, not medical advice.

## Requirements

- Windows 10/11, Python 3.10+ (64-bit), Node.js 18+, and npm.
- A camera is optional; image scans require a configured Gemini API key. Paste mode works without it.
- The MiniLM encoder is downloaded once at backend startup if its local folder is absent. The supplied classifier head stays local.

## Quick start (Windows PowerShell)

Run setup once from the project root:

```powershell
py -3 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
backend\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm --prefix frontend install
Copy-Item backend\.env.example backend\.env
```

Edit `backend\.env` and set `GEMINI_API_KEY` for photo OCR and generated ingredient information. Keep this key in the ignored `.env` file; never commit it. `GEMINI_MODEL` defaults to `gemini-3.5-flash`. Without a key, text scoring and history work; Gemini-dependent enrichment is unavailable.

Start both servers with one command from the project root:

```powershell
.\run_dev.bat
```

Open <http://localhost:5173>. The API docs are at <http://localhost:8000/docs>. To start services separately, use two terminals:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

```powershell
Set-Location frontend
npm run dev
```

The frontend reads `VITE_API_URL` from `frontend/.env`; its default is `http://localhost:8000`. The API creates and seeds the ignored `backend/data/nutrisnap.db` on startup.

## ML adapter files and activation

The MiniLM adapter expects these local, git-ignored files:

```text
backend/models/minilm-head/head.npz
backend/models/minilm-head/head_config.json
backend/models/minilm-encoder/config.json
backend/models/minilm-encoder/model.safetensors
backend/models/minilm-encoder/tokenizer.json
```

The tokenizer folder may also contain `tokenizer_config.json`, `special_tokens_map.json`, and `vocab.txt`. The head archive is numeric NPZ data with `coef` shaped `(4,384)`, `intercept` shaped `(4,)`, and `classes` equal to `[1,2,3,4]`; the JSON config identifies `sentence-transformers/all-MiniLM-L6-v2`, normalization, and those classes. Put the trained head files in `backend/models/minilm-head/`. On first startup the adapter downloads and saves the encoder to `backend/models/minilm-encoder/` if the complete local encoder is missing.

After installing CPU PyTorch and `backend/requirements.txt`, set these values in `backend/.env`:

```dotenv
ML_ENABLED=true
NOVA_BACKEND=minilm_head
NOVA_MODEL_DIR=backend/models/minilm-head
```

Restart the API and check `/api/health`. The adapter runs its 12-example startup self-test and is only reported ready if it passes. Otherwise requests continue with the rule score and health reports an error. Do not alter or bypass that gate; evaluate only on owner-supplied golden data.

`hf_nova.py` and the alternative MiniLM adapter stub remain placeholders. The configured `minilm_head` adapter is implemented, but the actual model head and encoder are local files and are not committed.

## Gemini and privacy

Set `GEMINI_API_KEY` only in `backend/.env`. Gemini is used for exact ingredient text extraction from images, summaries for ingredients missing from the owner knowledge base, and generic alternatives. It never changes the score. Provider failures fall back safely and do not return HTTP 500. Image bytes and full pasted text are not stored in history; saved results retain a redacted review for reopening. Scans and generated cache entries stay in the local SQLite file.

Pre-generate summary cache entries for knowledge-base ingredients and any owner-supplied golden products:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe scripts\warm_cache.py
```

This requires `GEMINI_API_KEY`; if it is missing, the script exits without making network requests. Only add real, owner-supplied ingredient lists to `app/data/golden/golden_products.json`; do not invent branded product data.

## Tests and demo data

Run from the project root:

```powershell
backend\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider backend\tests
backend\.venv\Scripts\python.exe backend\scripts\eval_golden.py
backend\.venv\Scripts\python.exe backend\scripts\init_db.py
backend\.venv\Scripts\python.exe backend\scripts\demo_queries.py
npm --prefix frontend run build
```

Gemini tests use mocks and make no network requests. See [docs/DATABASE.md](docs/DATABASE.md), [docs/QUERIES.sql](docs/QUERIES.sql), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/PRD.md](docs/PRD.md), and [docs/HANDOFF.md](docs/HANDOFF.md).

## Scope and limits

- Ingredient rules always produce the score; Gemini output never affects it. NOVA describes processing level, not toxicity.
- Ingredients missing from the knowledge base may not affect the score; the UI reports low coverage.
- Explanations and alternatives are informational, may be AI-generated, and are not medical advice.
- Open Food Facts information is attributed in the app. The golden-product file is intentionally empty until verified examples are supplied.
- Camera access requires a secure browser context (localhost qualifies) and user permission. Image requests are capped at 5 MB by the API; the frontend resizes images to at most 1280 px.