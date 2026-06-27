SQLCODER_PROMPT = """### Task
Generate a SQL query to answer [QUESTION]{question}[/QUESTION]

### Database Schema
The query will run on a database with the following schema:
{schema_text}

### Answer
Given the database schema, here is the SQL query that answers [QUESTION]{question}[/QUESTION]
[SQL]
"""

RETRY_SUFFIX = """
The previous query failed when executed against the real database:
{prior_error}

Fix the query so it runs without error, using only the tables and columns listed above.
"""


def build_sql_prompt(question: str, schema_text: str, prior_error: str | None = None) -> str:
    prompt = SQLCODER_PROMPT.format(question=question, schema_text=schema_text)
    if prior_error:
        prompt += RETRY_SUFFIX.format(prior_error=prior_error)
    return prompt


EXPLAIN_PROMPT = """A user asked: "{question}"

This SQL query was run to answer it:
{sql}

It returned these results (columns: {columns}):
{rows}

In one or two plain-language sentences, answer the user's question using these results. \
Do not mention SQL or the query itself.
"""


def build_explain_prompt(question: str, sql: str, columns: list[str], rows: list[tuple]) -> str:
    return EXPLAIN_PROMPT.format(question=question, sql=sql, columns=", ".join(columns), rows=rows)


# Chat-style equivalents for instruct/chat-completion models (e.g. via the
# NVIDIA/OpenAI-compatible API). These models weren't fine-tuned on
# sqlcoder's raw-completion [QUESTION]/[SQL] template -- they expect a
# system/user message split and respond better to plain instructions.

CHAT_SQL_SYSTEM = (
    "You are a PostgreSQL expert. Given a database schema and a question, "
    "write a single read-only SQL query (SELECT or WITH only) that answers it. "
    "Respond with ONLY the raw SQL -- no explanation, no markdown code fences."
)


def build_sql_chat_messages(
    question: str, schema_text: str, prior_error: str | None = None
) -> list[dict]:
    user_content = f"### Database Schema\n{schema_text}\n\n### Question\n{question}"
    if prior_error:
        user_content += (
            f"\n\nThe previous query failed when executed:\n{prior_error}\n"
            "Fix the query so it runs without error, using only the tables and columns above."
        )
    return [
        {"role": "system", "content": CHAT_SQL_SYSTEM},
        {"role": "user", "content": user_content},
    ]


CHAT_EXPLAIN_SYSTEM = (
    "You are a helpful data analyst. Given a question, the SQL used to answer it, and the "
    "resulting rows, respond with a one or two sentence plain-language answer. "
    "Do not mention SQL or the query itself."
)


def build_explain_chat_messages(
    question: str, sql: str, columns: list[str], rows: list[tuple]
) -> list[dict]:
    user_content = (
        f'Question: "{question}"\nSQL used: {sql}\n'
        f"Columns: {', '.join(columns)}\nRows: {rows}"
    )
    return [
        {"role": "system", "content": CHAT_EXPLAIN_SYSTEM},
        {"role": "user", "content": user_content},
    ]
