# NL to SQL

Ask a plain-English question about a database, get back a SQL query, the actual query result, and a natural-language answer.

```
"Which breed has the most dogs?"
        ↓
  schema introspection → LLM generates SQL → safety check → execute → explain result
```

This is a learning project built layer by layer, with each layer testable in isolation.

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

## Reliability tuning

Both backends' sampling temperature, token limits, and request timeouts are configurable via `.env` (`OLLAMA_TEMPERATURE`/`OLLAMA_TIMEOUT_SECONDS`, `API_TEMPERATURE`/`API_MAX_TOKENS`/`API_TIMEOUT_SECONDS`) rather than hardcoded.

The retry loop (`pipeline/retry.py`, `MAX_ATTEMPTS=4`) also escalates temperature on each retry via `llm/temperature.escalate()`: if a model gets deterministically stuck repeating the same wrong answer, a fixed temperature means every retry produces an identical result, making the retry pointless. Escalating temperature on each attempt gives later retries a real chance to land on something different.

## Safety

LLM-generated SQL is never trusted blindly. `pipeline/safety.py` rejects anything that isn't a single read-only `SELECT`/`WITH` statement *before* it reaches the database, and caps result size with an injected `LIMIT` if the model didn't add one. This guards against a natural-language question accidentally being translated into a destructive statement (e.g. "remove the churned customers" → `DELETE`).

## Evaluation dataset (not included)

This project was tested against a database from the [Spider](https://yale-lily.github.io/spider) text-to-SQL benchmark (the `dog_kennels` sample database). The full Spider dataset (~1.7GB) is not committed to this repo — download it separately from the Spider project page if you want to run broader evaluation.

## Project structure

```
config.py                  # env var loading
db/
  connection.py             # SQLAlchemy engine
  schema_introspect.py      # Layer 2: schema → text
llm/
  base.py                   # LLMBackend interface
  factory.py                 # picks a backend based on LLM_BACKEND in .env
  ollama_backend.py          # local sqlcoder via Ollama
  api_backend.py              # hosted OpenAI-compatible chat API (default: NVIDIA)
  extract.py                  # shared SQL-cleanup helper for both backends
pipeline/
  prompt_templates.py        # prompt construction
  safety.py                  # read-only query validation
  executor.py                 # runs SQL, returns rows or a structured error
  retry.py                    # error-correction loop
  explainer.py                 # result → natural-language answer
scripts/
  seed_db.py                   # creates and seeds the sample Postgres schema
app.py                         # Streamlit UI
```

## Known limitations

`sqlcoder` running locally (quantized, CPU/shared-GPU) is not perfectly reliable: it can pick wrong columns on ambiguous questions, occasionally writes a `GROUP BY` that's invalid under Postgres's strict SQL standard enforcement (even though the same query is accepted by SQLite's looser rules), and its explanation step sometimes echoes a SQL fragment instead of a sentence since it's fine-tuned for SQL generation, not prose. The retry loop and read-only safety check exist to make these failures *safe* (no crash, no destructive query, no silently wrong-looking success) rather than to eliminate them.

For the full build narrative, including every bug found and how it was diagnosed, see [BUILD_LOG.md](BUILD_LOG.md).
