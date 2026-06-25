# Build Log

A chronological record of how this project was built, and every problem hit along the way. Written as a learning project — the point of this file is to keep the *why* behind decisions and the *root cause* of each bug, not just the final code.

## 1. Initial scope and architecture decisions

Started from a 5-layer NL-to-SQL design: input → schema serialization → LLM SQL generation → safe execution → natural-language output. Two adjustments were made to the original tech-stack spec before writing any code:

- **LLM**: `defog/sqlcoder-7b` via the free HuggingFace Inference API isn't reliable for a 7B model, and a paid HF Inference Endpoint wasn't worth it for a learning project. Settled on running `sqlcoder` **locally via Ollama** (`http://localhost:11434`) — free, private, no GPU strictly required. The LLM call sits behind an abstract `LLMBackend` interface (`llm/base.py`) so a hosted API backend could be swapped in later without touching the pipeline.
- **Database**: schema is introspected at runtime, so the system doesn't need to be told the schema in advance — it works against whatever database `DATABASE_URL` points to.

## 2. Layer 2 — schema introspection

**Plan said**: query `information_schema` directly. **Reality**: `information_schema` is a Postgres/standard-SQL feature that SQLite doesn't implement (it uses `sqlite_master` instead). Since testing started against a SQLite fixture and Postgres was the eventual target, `db/schema_introspect.py` uses SQLAlchemy's `inspect()` reflection API instead — one dialect-agnostic Python API that works against both.

Verified in isolation by running it directly against the Spider benchmark's `dog_kennels.sqlite` (a pre-existing dataset found in `spider_data/`, used as a free test fixture before a real Postgres DB was available) — confirmed it correctly captured primary keys and foreign key relationships.

## 3. Layer 3 — LLM backend (Ollama + sqlcoder)

Pulled `sqlcoder` via `ollama pull sqlcoder` (4.1GB, quantized 7B model). Three real bugs surfaced during testing:

### Bug: stray `[SQL]`/`[/SQL]` tags leaking into extracted SQL
The official sqlcoder prompt template ends with the literal token `[SQL]`. The model often echoes this token back — sometimes as `[/SQL]` after its answer, sometimes as `[SQL]` again, inconsistently. The first version of `_extract_sql()` only stripped `[/SQL]`, so a stray `[SQL]` left in the output caused the safety validator to reject otherwise-correct SQL. **Fix**: regex-strip both `[SQL]` and `[/SQL]` (case-insensitive) anywhere in the text.

### Bug: `temperature=0` deterministically got stuck on a wrong answer
First attempt used `temperature=0` (greedy decoding) for reproducibility. Testing the same question ("Which breed has the most dogs?") repeatedly showed the model deterministically returning a non-SQL "hint" paragraph instead of a query — *every single time*, because greedy decoding always picks the same highest-probability token path, and that path happened to be a bad one for this prompt. This also broke the retry loop: since generation is deterministic, every retry produced the identical wrong output, so retrying was useless.

**Fix**: switched to `temperature=0.3`. Verified across 5 trials this gave ~60% correct SQL vs ~40% degenerate hints — enough variance that a 3-attempt retry loop has a real chance of escaping a bad output, while staying low enough to mostly track the model's best guess.

### Bug: explainer echoing markdown headers / SQL fragments
sqlcoder is fine-tuned for writing SQL, not prose. Asking it to explain a result (Layer 5) sometimes produced an answer prefixed with a header like `### Answer #:`, and was fixed by stripping leading `#`-headers. Later, against the real Postgres data, it sometimes returned a bare SQL fragment like `"NULLS LAST"` instead of a sentence — a deeper instance of the same root cause (the model isn't a general-purpose writer) that the header-stripping fix doesn't catch. Documented as a known limitation rather than patched further, since fixing it properly would mean using a different model for the explanation step.

## 4. Layer 4 — safety and retry

`pipeline/safety.py` blocks anything that isn't a single read-only `SELECT`/`WITH`. Deliberately a keyword blocklist + regex, not a full SQL parser — the threat model here is "LLM mistranslates English into a destructive statement," not "malicious user crafts an adversarial injection payload," so a lightweight check is proportionate.

Verified by feeding it a `DELETE FROM Dogs WHERE 1=1` directly — correctly rejected before reaching the database.

`pipeline/retry.py` returns errors as values (`PipelineResult` / `PipelineFailure` dataclasses) rather than raising exceptions, since an LLM-generated query failing is an expected, common outcome that the loop needs to inspect and act on, not exceptional control flow.

## 5. Streamlit UI

Built `app.py` with `@st.cache_resource` for the LLM backend and `@st.cache_data` for the schema text, since Streamlit reruns the whole script on every interaction — without caching, both would be recreated on every keystroke.

Verified the server actually serves the app via `curl localhost:8501` (returned valid Streamlit HTML). Could not drive it through an actual browser interaction during the build since the Chrome MCP extension wasn't connected in this session — that remains a manual verification step for the user.

## 6. GitHub repo

Created `.gitignore` excluding `.claude/`, `.env`, `__pycache__/`, `.DS_Store`, and `spider_data/`. The Spider dataset is 1.7GB and is a separately-distributed academic benchmark, not something to redistribute inside a personal repo — documented in the README instead of committed.

Pushed to `https://github.com/SouhailBourhim/nl-to-sql` (public), single commit, no AI co-author trailer per explicit instruction.

## 7. Virtual environment correction

Dependencies had initially been installed with plain global `pip install` commands during early testing — flagged by the user as bad practice. Corrected by creating `venv/` and reinstalling all dependencies inside it; added `venv/` to `.gitignore`. All subsequent commands run with the venv activated.

## 8. Real Postgres database

### Decision: Docker over Homebrew
A `brew install postgresql@16` attempt was declined by the user in favor of a disposable Docker container — cleaner, fully isolated, no system-level service to manage afterward.

### Problem: Docker daemon not running
`docker ps` initially failed — Docker Desktop's daemon wasn't started. Fixed with `open -a Docker`, then polled `docker ps` in a loop until it responded.

### Schema design
Built `scripts/seed_db.py` to create and seed a schema matching the original churn-analysis example from the spec: `plans`, `customers` (with `status`/`churn_date`), `recharges`. Seeded 60 synthetic customers (19 churned), 3 plans, 344 recharges with realistic date ranges relative to the current date.

### Problem: `ModuleNotFoundError: No module named 'db'`
Running `python scripts/seed_db.py` directly failed because `db/` is a top-level package relative to the project root, not to `scripts/`. **Fix**: run with `PYTHONPATH=.` so the project root is on the import path.

### Problem: repeated Ollama timeouts against the real DB
Several consecutive runs hit `ReadTimeout` at the hardcoded 120s limit. Diagnosis via `ollama ps` and `top` showed the model was loaded (93% on GPU) but the system was under heavy memory pressure (120MB free) and high load average (~10.5), with Docker Desktop's VM, Postgres, and Ollama all competing for resources simultaneously. A bare `curl` test to the Ollama API (bypassing the pipeline) succeeded in ~31s once warmed up, confirming the model itself worked — the issue was insufficient timeout margin under real system load, not a bug in the request. **Fix**: raised the timeout in `llm/ollama_backend.py` from 120s to 240s.

### Problem: Postgres container exited mid-session
A pipeline run failed with `psycopg2.OperationalError: connection refused`. `docker logs nl_to_sql_pg` showed a clean shutdown (exit code 0) with a large gap in container-internal timestamps — consistent with the host Mac sleeping during a long wait on a slow model call, which Docker Desktop's VM doesn't survive cleanly. **Fix**: `docker start nl_to_sql_pg`; confirmed the data volume was intact (60 customers, 344 recharges still present) since the container was restarted, not recreated.

### Finding: SQLite-valid SQL can be invalid under Postgres
Asking "Which customers churned and had more than 5 recharges?" repeatedly produced:
```sql
SELECT c.first_name, c.last_name FROM customers AS c
JOIN recharges AS r ON c.customer_id = r.customer_id
GROUP BY c.first_name, c.last_name
HAVING COUNT(r.recharge_id) > 5 AND c.churn_date IS NOT NULL
```
This is invalid under the SQL standard — `c.churn_date` appears in `HAVING` without being in `GROUP BY` or wrapped in an aggregate — and Postgres rejects it with a `GroupingError`. SQLite is lenient about this and would have accepted it silently, which is why this never appeared during the earlier SQLite-based testing. The retry loop fed the exact Postgres error back to the model three times, but the model repeated the same mistake each time and the pipeline correctly reported a clean failure rather than crashing or returning wrong data — the safety net did its job even though the model couldn't self-correct this particular error class.

A simpler question ("How many customers are on each plan?") succeeded correctly against the same database (24 Basic / 18 Standard / 18 Premium), confirming the happy path works end-to-end against the real Postgres database.

## Open items / known limitations (not yet fixed)

- Explainer step occasionally returns a SQL fragment instead of a sentence (sqlcoder is not a prose model).
- Model cannot always self-correct Postgres's stricter `GROUP BY` enforcement even when given the exact error.
- UI has not been manually click-tested in a real browser session.
- No automated evaluation harness yet (Spider dataset is present on disk but unused for this).
