# NutriSnap local database

The demo uses Python's standard `sqlite3` module with foreign keys enabled. `backend/data/nutrisnap.db` is local and git-ignored. Only scores, fallback metadata, and parsed ingredient names/IDs are stored. Submitted ingredient text and user identifiers are never stored.

## Why SQLite

SQLite fits this embedded, single-node presentation: it needs no database server, provides ACID transactions and standard SQL, and stores the demo in one local file. WAL mode allows concurrent readers while SQLite serializes its single writer; it is not intended for high write concurrency across multiple app servers. Every connection enables WAL and foreign keys.

The tables follow a 3NF-style design: ingredients and aliases are separate, scoring rules are keyed by flag, scans hold scan-level facts, and scan ingredients hold the many-to-many scan detail. Optional generated summaries and alternatives use separate caches. Full submitted text and images are never stored; `scan.result_json` contains the review fields needed to reopen a result, with OCR `detected_text` removed. The reserved nullable `user_id` is unused.

For a hosted multi-user deployment, migrate to PostgreSQL: retain the normalized tables, replace SQLite-specific date/WAL behavior with PostgreSQL types and transactions, add indexes/constraints in a migration, and use a connection pool. Keep image and full-text retention out of the schema unless a separately reviewed privacy requirement is introduced.

```mermaid
erDiagram
  ingredient ||--o{ ingredient_alias : has
  ingredient ||--o{ scan_ingredient : matched_as
  scan ||--o{ scan_ingredient : contains
  flag_rule ||--o{ scan_ingredient : classifies
  ingredient_info }o--o{ ingredient : describes
  ingredient { TEXT id PK; TEXT canonical; TEXT category; TEXT primary_flag; INTEGER verified }
  ingredient_alias { INTEGER id PK; TEXT ingredient_id FK; TEXT alias; TEXT kind }
  flag_rule { TEXT flag PK; REAL penalty; INTEGER position_weighted; INTEGER is_bonus }
  scan { INTEGER id PK; TEXT created_at; INTEGER score; TEXT band; TEXT scoring_method; TEXT fallback_reason; INTEGER nova_top; REAL nova_confidence; INTEGER rule_score; INTEGER ml_score; REAL kb_coverage; INTEGER n_tokens; TEXT source; TEXT result_json; INTEGER user_id }
  scan_ingredient { INTEGER id PK; INTEGER scan_id FK; INTEGER position; TEXT raw_name; TEXT ingredient_id FK; TEXT flag; REAL points }
  ingredient_info { TEXT name_norm PK; TEXT what_it_is; TEXT health_note; TEXT concern_level; TEXT source; TEXT model; TEXT generated_at; INTEGER hit_count; INTEGER verified }
  alternative_cache { TEXT cache_key PK; TEXT content_json; TEXT source; TEXT model; TEXT generated_at; INTEGER hit_count; INTEGER verified }
```

Initialize or reseed with `python scripts/init_db.py` from `backend`. Seeding is idempotent. Demo query definitions are in `docs/QUERIES.sql`; `GET /api/queries` returns each title and live result rows. `demo_queries.py` also displays an indexed query plan.
