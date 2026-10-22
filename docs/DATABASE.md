# NutriSnap local database

The demo uses Python's standard `sqlite3` module with foreign keys enabled. `backend/data/nutrisnap.db` is local and git-ignored. Only scores, fallback metadata, and parsed ingredient names/IDs are stored. Submitted ingredient text and user identifiers are never stored.

```mermaid
erDiagram
  ingredient ||--o{ ingredient_alias : has
  ingredient ||--o{ scan_ingredient : matched_as
  scan ||--o{ scan_ingredient : contains
  flag_rule ||--o{ scan_ingredient : classifies
  ingredient { TEXT id PK; TEXT canonical; TEXT category; TEXT primary_flag; INTEGER verified }
  ingredient_alias { INTEGER id PK; TEXT ingredient_id FK; TEXT alias; TEXT kind }
  flag_rule { TEXT flag PK; REAL penalty; INTEGER position_weighted; INTEGER is_bonus }
  scan { INTEGER id PK; TEXT created_at; INTEGER score; TEXT band; TEXT scoring_method; TEXT fallback_reason; INTEGER nova_top; REAL nova_confidence; INTEGER rule_score; INTEGER ml_score; REAL kb_coverage; INTEGER n_tokens }
  scan_ingredient { INTEGER id PK; INTEGER scan_id FK; INTEGER position; TEXT raw_name; TEXT ingredient_id FK; TEXT flag; REAL points }
```

Initialize or reseed with `python scripts/init_db.py` from `backend`. Seeding is idempotent. Demo query definitions are in `docs/QUERIES.sql`; `GET /api/queries` returns each title and live result rows.
