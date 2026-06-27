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

## 9. Second LLM backend — hosted API (NVIDIA)

The user provided an NVIDIA API key and asked to try it as the backend. NVIDIA's `build.nvidia.com` exposes an OpenAI-compatible chat-completions endpoint, so this was implemented as a second `LLMBackend` rather than a one-off script:

- `llm/extract.py`: pulled the SQL-cleanup logic (stripping ` ```sql ` fences and stray `[SQL]`/`[/SQL]` tokens) out of `ollama_backend.py` into a shared module, since the new backend needed the same cleanup.
- `pipeline/prompt_templates.py`: added `build_sql_chat_messages` / `build_explain_chat_messages` — a system/user message-pair format, distinct from sqlcoder's raw-completion template. General instruct models weren't fine-tuned on the `[QUESTION]...[SQL]` template and respond better to plain chat instructions.
- `config.py`: replaced the placeholder `OPENAI_API_KEY`/`OPENAI_MODEL` settings with generic `API_BASE_URL` / `API_KEY` / `API_MODEL`, defaulting to NVIDIA's endpoint and a guessed model id (`meta/llama-3.1-70b-instruct`).
- `llm/api_backend.py`: new `ApiBackend` implementation.
- `llm/factory.py`: new — `get_backend()` picks `OllamaBackend` or `ApiBackend` based on `LLM_BACKEND` in `.env`, so `app.py` no longer hardcodes a specific backend.

The model id guess was verified correct on the first live API call (a trivial "say hello" request returned `200` with `"model":"meta/llama-3.1-70b-instruct"` echoed back).

**Result**: both test questions — including "Which customers churned and had more than 5 recharges?", the exact question that defeated `sqlcoder` after 3 retries against Postgres (see the `GroupingError` finding above) — succeeded on the **first attempt** with this backend, with correct `GROUP BY`/`HAVING` structure and clean, well-formed natural-language explanations (no fragment leakage). This is a direct, concrete payoff of having built the `LLMBackend` abstraction early: swapping the model required zero changes to the prompt-construction pattern's *call sites*, the safety check, the retry loop, or the executor — only a new backend implementation and one `.env` value (`LLM_BACKEND=api`).

The Postgres container had also stopped again during this stretch of the session (same root cause as before — the Mac went to sleep) and needed another `docker start nl_to_sql_pg`; data was intact both times.

## 10. PR review fixes and reliability hardening

A Sourcery automated review on the NVIDIA-backend PR flagged three real issues, all fixed and pushed to the same branch:
- `ApiBackend._chat` assumed an OpenAI-style success payload and would raise an opaque `KeyError`/`IndexError` on any unexpected response shape. Fixed by validating `choices`/`message`/`content` exist with the right types before indexing, raising a `RuntimeError` with the raw payload otherwise.
- `extract_sql`'s fence regex only matched ` ```sql ` fences; plain untagged ` ``` ` fences (common from chat models) passed straight through. Broadened to `` ```(?:sql)?\s*(.*?)``` ``.
- `llm/factory.get_backend` silently fell back to `OllamaBackend` for any `LLM_BACKEND` value other than exactly `"api"`, so a typo like `LLM_BACKEND=API` would silently switch backends. Fixed by validating against a whitelist and raising `ValueError` on anything else.

Separately, addressed the "reliability" improvements identified earlier in this log:
- **Configurable generation params**: `ApiBackend` had `temperature`, `max_tokens`, and `timeout` hardcoded (also flagged by Sourcery). Moved to `config.py` as `API_TEMPERATURE`/`API_MAX_TOKENS`/`API_TIMEOUT_SECONDS`, with matching `OLLAMA_TEMPERATURE`/`OLLAMA_TIMEOUT_SECONDS` added for the other backend too, for consistency.
- **Temperature escalation across retries**: previously every retry attempt used the same fixed temperature, so a model that landed on a bad answer (the "stuck" behavior documented in section 3) had no real chance to produce something different on retry 2 or 3. Added `LLMBackend.generate_sql`'s `attempt` parameter (threaded through from `pipeline/retry.py`) and `llm/temperature.escalate()`, which raises temperature by `0.2` per attempt up to a cap of `0.9`. Both backends now use this.
- **`MAX_ATTEMPTS` bumped from 3 to 4**, giving the escalation a bit more room since the cost of an extra attempt is low.

Explicitly *not* done yet (flagged as a bigger design decision, not implemented speculatively): splitting SQL generation and explanation across different backends (e.g. always use the API backend for `explain_result` even when Ollama is selected for SQL generation), since `sqlcoder` is fine-tuned for SQL and weaker at prose. Noted as a future option rather than built, since it changes the backend-selection model from "one model for everything" to "per-task model routing."

## 11. Safety hardening: known-table validation and statement timeout

Addressed the two safety improvements identified earlier in this log:

- **Known-table validation** (`pipeline/safety.py:validate_known_tables`): regex-extracts identifiers following `FROM`/`JOIN`, normalizes schema-qualified names (`public.customers` → `customers`), excludes CTE-defined names (`WITH foo AS (...)`) since those are locally scoped rather than real tables, and checks the rest against `db.schema_introspect.get_known_tables()` (a new function returning the lowercased real table names from SQLAlchemy's inspector). A hallucinated table name now fails fast with a clear message naming the bad table, instead of a confusing database-level "relation does not exist" error after a wasted round trip. Verified directly: `SELECT * FROM invoices` against the seeded DB (which has no `invoices` table) returns `Query references unknown table(s): invoices. Known tables: customers, plans, recharges.`
- **Statement timeout** (`pipeline/executor.py`): `ensure_row_limit` only bounds rows *returned* — an unfiltered query can still scan an entire large table before that limit applies. Added `SET statement_timeout = <STATEMENT_TIMEOUT_MS>` on the connection before executing (Postgres-only; skipped for SQLite, which has no equivalent). Verified the setting actually takes effect with `SHOW statement_timeout`.

`pipeline/retry.py` now fetches `known_tables` once per question (not once per retry attempt) and passes it into `execute_sql`, avoiding a redundant schema-introspection call on every retry.

Also added `tests/test_safety.py` — the first real test file in the project (previously an empty stub). 11 unit tests covering `validate_read_only`, `validate_known_tables`, and `ensure_row_limit`; all pure logic, no DB or LLM dependency, so they run instantly and don't need Ollama/Postgres/NVIDIA reachable. Added `pytest` to `requirements.txt`.

Re-ran the full pipeline against the real Postgres DB after these changes to confirm the happy path still works unaffected — it does.

## 12. Offline integration test suite

Addressed the "no automated evaluation harness" / "tests depend on live infra" gap identified earlier. Rather than building the Spider-benchmark harness (a bigger, separate undertaking -- still open below), focused on a more immediately useful gap: there was no way to test the pipeline's control flow (retry behavior, safety enforcement, explainer wiring) without a live model and a running Postgres container.

- `tests/conftest.py`: sets `DATABASE_URL` to a throwaway SQLite file *before* `config.py` (or anything importing it) is loaded anywhere in the test session, then creates and seeds a small schema in a session-scoped fixture. The ordering matters -- `config.DATABASE_URL` and `db/connection.py`'s `engine` are both bound once at import time, so the env var has to be set first or the test suite would silently hit whatever `.env` points at (the real Postgres DB).
- `tests/fakes.py`: `FakeLLMBackend`, a canned-response `LLMBackend` implementation. Takes a list of SQL strings (one per retry attempt) and a canned explanation, and records every call it receives -- enough to script scenarios like "wrong query on attempt 1, corrected query on attempt 2" and assert the retry loop actually retried rather than just inspecting final output.
- `tests/test_pipeline_integration.py`: 6 tests covering the full `generate_and_execute` flow -- first-attempt success, retry-then-succeed, exhausting all retries, a destructive query being blocked outright (never even reaching a retry), the explainer being wired correctly, and `execute_sql` rejecting a hallucinated table.
- `pytest.ini`: added `pythonpath = .` so `pytest` works directly without manually exporting `PYTHONPATH=.` first.

Verified the independence claim directly: stopped the Postgres container (`docker stop nl_to_sql_pg`) and reran the full suite -- all 17 tests (11 from `test_safety.py` + 6 new ones) still passed in under 0.05s, then restarted the container.

## 13. Spider benchmark accuracy harness

Built `scripts/evaluate_spider.py` to close the remaining testing gap: the offline test suite (section 12) covers pipeline *control flow* with a fake backend, not real-model *accuracy*. This script runs actual Spider questions through the live pipeline (whichever `LLM_BACKEND` is configured) against the matching Spider SQLite database, and compares the result rows to Spider's gold SQL run on the same database. Execution accuracy (does the data match), not exact-string match, since two different SQL queries can be equally correct.

Same `DATABASE_URL`-before-any-import ordering trick as `tests/conftest.py` is used here too, pointed at `spider_data/database/<db>/<db>.sqlite` instead of a throwaway fixture. The row-comparison is a simplification of Spider's official metric (sorts each row's own values, then sorts the row list -- order- and column-position-insensitive, but not as rigorous as the official column-permutation handling); good enough for a learning-project sanity check, not a publishable benchmark number.

### Bug found while running it: a live rate limit crashed the whole evaluation run

Running against 20 `dog_kennels` questions back-to-back hit NVIDIA's free-tier rate limit (`429 Too Many Requests`) partway through, and the entire script crashed rather than just failing that one question. Tracing why surfaced a real gap, not just an eval-script inconvenience: `pipeline/retry.py`'s loop only ever caught *SQL execution* errors (`ExecutionError` from `execute_sql`) -- if `backend.generate_sql` itself raised (network error, rate limit, malformed API response), the exception propagated straight up and would have crashed the Streamlit app the same way in production, not just this script.

Fixed at two levels:
- `pipeline/retry.py`: wrapped the `backend.generate_sql` call in `try/except`, treating any exception as a retryable failure (same as a bad-SQL execution error) rather than letting it crash the request.
- `llm/api_backend.py`: added transport-level retry-with-backoff specifically for `429` responses inside `_chat` (respects `Retry-After` if present, otherwise a short fixed backoff, capped at 3 retries). This is handled separately from the pipeline-level retry because a rate limit is a transient *infrastructure* issue, not the model producing bad SQL -- retrying transparently at the transport layer means it doesn't burn one of the limited logical attempts that `MAX_ATTEMPTS` budgets for actual SQL-correction retries.

Added `tests/test_api_backend.py` (mocks `requests.post`, no real network call) verifying the 429-retry-then-succeed path, the exhausted-retries path, and that a non-429 error (e.g. 500) is *not* retried. Added two more cases to `tests/test_pipeline_integration.py` using a `FakeLLMBackend` extended with a `raise_on_attempts` parameter, confirming the pipeline recovers from a mid-sequence backend exception and fails cleanly (not with a crash) if the backend always raises.

### Result

Reran the harness after the fix: 15 `dog_kennels` questions completed without crashing, **11/15 (73.3%) execution-accuracy match**, 2 genuine generation failures, 2 genuine mismatches. This is the first repeatable, scriptable accuracy number for the project -- everything before this was spot-checking a handful of hand-picked questions.

## Open items / known limitations (not yet fixed)

- Explainer step occasionally returns a SQL fragment instead of a sentence when using the `sqlcoder`/Ollama backend (sqlcoder is not a prose model). Not observed with the `api` backend in testing so far.
- The `sqlcoder`/Ollama backend cannot always self-correct Postgres's stricter `GROUP BY` enforcement even when given the exact error; the `api` backend resolved the same question correctly without needing a retry.
- UI has not been manually click-tested in a real browser session.
- The Spider harness's row-comparison metric is a simplification of the official Spider execution-accuracy metric, not a byte-for-byte reproduction -- don't quote its accuracy numbers as directly comparable to published Spider leaderboard results.
- The NVIDIA `API_MODEL` default (`meta/llama-3.1-70b-instruct`) was chosen as an educated guess and only spot-checked with a couple of questions — not yet run through a broader test set.
