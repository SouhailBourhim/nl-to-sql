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
