# NL to SQL

Ask a plain-English question about a database, get back a SQL query, the actual query result, and a natural-language answer.

```mermaid
flowchart LR
    Q(["💬 'Which breed has<br/>the most dogs?'"]) --> S["1 · Schema introspection"]
    S --> G["2 · LLM generates SQL"]
    G --> C{"3 · Safety check"}
    C -- blocked --> X(["❌ Rejected"])
    C -- passes --> E["4 · Execute SQL"]
    E -- error --> G
    E -- success --> O["5 · Explain result"]
    O --> A(["✅ Plain-English answer"])
```

This is a learning project built layer by layer, with each layer testable in isolation. The `4 → 2` loop is the retry path: a failed execution feeds its error back into the next generation attempt (see [Reliability tuning](#reliability-tuning)).

## Architecture

| Layer | What it does | Code |
|---|---|---|
| 1. Input | Plain-English question from the user | `app.py` |
| 2. Schema | Introspects the connected database's tables/columns/keys at runtime and serializes them as `CREATE TABLE` text for the prompt | `db/schema_introspect.py` |
| 3. LLM | Generates SQL from the question + serialized schema | `llm/`, `pipeline/prompt_templates.py` |
| 4. Execution | Validates the SQL is read-only, runs it, retries with the error fed back to the LLM if it fails | `pipeline/safety.py`, `pipeline/executor.py`, `pipeline/retry.py` |
| 5. Output | Turns the result rows into a one/two-sentence plain-language answer | `pipeline/explainer.py` |

The LLM call goes through an abstract `LLMBackend` interface (`llm/base.py`), so the model behind it can be swapped via one config value (`LLM_BACKEND` in `.env`) without touching the pipeline. `llm/factory.py` picks the implementation at runtime.

## Two LLM backends

| `LLM_BACKEND` | Implementation | Notes |
|---|---|---|
| `ollama` (default) | `llm/ollama_backend.py` — local [`sqlcoder`](https://github.com/defog-ai/sqlcoder) via [Ollama](https://ollama.com) | Free, private, no data leaves your machine. A quantized 7B model running on CPU/shared-GPU — not perfectly accurate (see Known limitations). |
| `api` | `llm/api_backend.py` — any OpenAI-compatible chat-completion API, defaults to [NVIDIA's hosted endpoint](https://build.nvidia.com) | Needs `API_KEY` in `.env`. In testing, a 70B instruct model via this path produced correct SQL and clean explanations on the first attempt for questions where `sqlcoder` needed retries or failed outright (see BUILD_LOG.md). |

Both backends implement the same `LLMBackend` interface (`generate_sql`, `explain_result`) but use different prompt shapes under the hood: `sqlcoder` is a raw-completion model fine-tuned on a specific `[QUESTION]...[SQL]` template (`pipeline/prompt_templates.py`'s `SQLCODER_PROMPT`), while general instruct models expect a system/user chat message split (`build_sql_chat_messages` / `build_explain_chat_messages` in the same file). The retry loop and safety check apply identically regardless of which backend produced the SQL.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install Ollama (https://ollama.com), then pull the model once:
ollama pull sqlcoder

cp .env.example .env
# edit .env: point DATABASE_URL at a SQLite file or a Postgres database
# to use the hosted API backend instead of local Ollama, set LLM_BACKEND=api and API_KEY=...
```

`DATABASE_URL` works with any SQLAlchemy-supported database. Examples:

```
# SQLite
DATABASE_URL=sqlite:///path/to/file.sqlite

# Postgres
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/dbname
```

### Sample Postgres database

A disposable Postgres instance plus a sample `customers`/`plans`/`recharges` schema (matching the churn-analysis example above) is included for local testing:

```bash
docker run -d --name nl_to_sql_pg \
  -e POSTGRES_USER=nltosql -e POSTGRES_PASSWORD=nltosql -e POSTGRES_DB=nltosql \
  -p 5432:5432 postgres:16

# set DATABASE_URL=postgresql+psycopg2://nltosql:nltosql@localhost:5432/nltosql in .env, then:
PYTHONPATH=. python scripts/seed_db.py
```

See [`scripts/seed_db.py`](scripts/seed_db.py) for the schema definition and synthetic data generation.

## Run

Always activate the venv first: `source venv/bin/activate`.

```bash
streamlit run app.py
```

Or run the pipeline directly without the UI (note `PYTHONPATH=.` so the top-level packages resolve when running a script from a subdirectory):

```bash
PYTHONPATH=. python - <<'EOF'
from db.schema_introspect import get_schema_text
from llm.factory import get_backend
from pipeline.retry import generate_and_execute

schema = get_schema_text()
backend = get_backend()  # picks Ollama or the API backend based on LLM_BACKEND in .env
outcome = generate_and_execute(backend, "Which breed has the most dogs?", schema)
print(outcome)
EOF
```

## Testing

```bash
pytest
```

The suite (`tests/`) runs entirely offline — no Ollama, no NVIDIA API, no Docker/Postgres needed. `tests/conftest.py` points `DATABASE_URL` at a throwaway SQLite file (created and torn down per test session) before `config.py` is ever imported, so it never touches your real database. `tests/fakes.py` provides `FakeLLMBackend`, a canned-response stand-in for `LLMBackend` that lets `test_pipeline_integration.py` exercise the full generate → safety-check → execute → retry → explain flow deterministically — including scripting "wrong query, then a corrected one" to test the retry loop without depending on a real model's behavior. `test_safety.py` covers the safety checks in isolation.

## Reliability tuning

Both backends' sampling temperature, token limits, and request timeouts are configurable via `.env` (`OLLAMA_TEMPERATURE`/`OLLAMA_TIMEOUT_SECONDS`, `API_TEMPERATURE`/`API_MAX_TOKENS`/`API_TIMEOUT_SECONDS`) rather than hardcoded.

The retry loop (`pipeline/retry.py`, `MAX_ATTEMPTS=4`) also escalates temperature on each retry via `llm/temperature.escalate()`: if a model gets deterministically stuck repeating the same wrong answer, a fixed temperature means every retry produces an identical result, making the retry pointless. Escalating temperature on each attempt gives later retries a real chance to land on something different.

## Safety

LLM-generated SQL is never trusted blindly. `pipeline/safety.py` runs three checks before a query reaches the database:

1. **Read-only enforcement** — rejects anything that isn't a single `SELECT`/`WITH` statement. Guards against a natural-language question accidentally being translated into a destructive statement (e.g. "remove the churned customers" → `DELETE`).
2. **Known-table validation** — rejects a query referencing a table name that doesn't exist in the introspected schema, with a clear error naming the bad table instead of a confusing database-level error. Catches a model hallucinating a table name before wasting a round trip.
3. **Row limit** — caps result size with an injected `LIMIT` if the model didn't add one.

These are regex-based checks, not a full SQL parser — proportionate to the actual threat model (an LLM mistranslating English into a wrong query), not an adversarial attacker crafting an injection payload.

A fourth guard lives in `pipeline/executor.py`: a Postgres `statement_timeout` (`STATEMENT_TIMEOUT_MS` in `.env`, default 5000ms) is set on every connection before executing. The row limit only bounds rows *returned* — an unfiltered query can still scan an entire large table before that limit ever applies — so the timeout bounds actual execution cost regardless of how the query is shaped.

## Accuracy evaluation (Spider benchmark)

`pytest` (above) tests pipeline *control flow* with canned responses. To measure real model *accuracy*, `scripts/evaluate_spider.py` runs actual questions from the [Spider](https://yale-lily.github.io/spider) text-to-SQL benchmark through the live pipeline (whichever `LLM_BACKEND` is configured) and checks whether the result matches Spider's gold SQL when run against the same database:

```bash
PYTHONPATH=. python scripts/evaluate_spider.py --db dog_kennels --limit 20
```

This makes live LLM calls and is not part of the `pytest` suite. The full Spider dataset (~1.7GB, includes the `dog_kennels` SQLite database used above) is not committed to this repo — download it separately from the Spider project page.

The match check is execution accuracy with a simplification: each row's values are sorted before comparing rows (order-insensitive on both rows and columns within a row), which is looser than Spider's official column-permutation-aware metric but adequate for a learning-project sanity check rather than a publishable benchmark number.

## Project structure

```
.
├── app.py                              Streamlit UI
├── config.py                           env var loading
│
├── db/
│   ├── connection.py                   SQLAlchemy engine
│   └── schema_introspect.py            Layer 2: schema → text
│
├── llm/
│   ├── base.py                         LLMBackend interface
│   ├── factory.py                      picks a backend based on LLM_BACKEND in .env
│   ├── ollama_backend.py               local sqlcoder via Ollama
│   ├── api_backend.py                  hosted OpenAI-compatible chat API (default: NVIDIA)
│   └── extract.py                      shared SQL-cleanup helper for both backends
│
├── pipeline/
│   ├── prompt_templates.py             prompt construction
│   ├── safety.py                       read-only + known-table validation
│   ├── executor.py                     runs SQL, returns rows or a structured error
│   ├── retry.py                        error-correction loop
│   └── explainer.py                    result → natural-language answer
│
├── scripts/
│   ├── seed_db.py                      creates and seeds the sample Postgres schema
│   └── evaluate_spider.py              real-model accuracy check against Spider benchmark
│
└── tests/
    ├── conftest.py                     throwaway SQLite fixture for offline tests
    ├── fakes.py                        FakeLLMBackend, a canned-response LLMBackend
    ├── test_safety.py                  unit tests for pipeline/safety.py
    ├── test_pipeline_integration.py    full pipeline flow against the fixture DB
    └── test_api_backend.py             rate-limit retry logic (mocked HTTP)
```

## Known limitations

- **`ollama`/`sqlcoder` accuracy** — a quantized 7B model running on CPU/shared-GPU is not perfectly reliable: it can pick wrong columns on ambiguous questions, occasionally writes a `GROUP BY` that's invalid under Postgres's strict SQL standard enforcement (even though the same query is accepted by SQLite's looser rules), and its explanation step sometimes echoes a SQL fragment instead of a sentence since it's fine-tuned for SQL generation, not prose. The retry loop and safety checks exist to make these failures *safe* (no crash, no destructive query, no silently wrong-looking success), not to eliminate them.
- **NVIDIA model choice** — `API_MODEL`'s default (`meta/llama-3.1-70b-instruct`) was an educated guess, only spot-checked and run through the Spider harness on a small sample. Not validated at scale.
- **Eval metric is a simplification** — `scripts/evaluate_spider.py`'s execution-accuracy check is order/column-position-insensitive but not as rigorous as Spider's official metric. Treat its output as a sanity check, not a leaderboard-comparable number.
- **UI not manually browser-tested** in this build process — `streamlit run app.py` has been confirmed to serve correctly, but the actual click-through experience hasn't been verified end-to-end.

For the full build narrative, including every bug found and how it was diagnosed, see [BUILD_LOG.md](BUILD_LOG.md).
