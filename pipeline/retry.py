from dataclasses import dataclass

from db.schema_introspect import get_known_tables
from llm.base import LLMBackend
from pipeline.executor import ExecutionError, ExecutionResult, execute_sql

MAX_ATTEMPTS = 4


@dataclass
class PipelineResult:
    sql: str
    result: ExecutionResult
    attempts: int


@dataclass
class PipelineFailure:
    last_sql: str
    last_error: str
    attempts: int


def generate_and_execute(
    backend: LLMBackend, question: str, schema_text: str
) -> PipelineResult | PipelineFailure:
    """Why feed the error back to the LLM instead of just failing: a wrong
    column name or join is something the model can usually fix once it sees
    the database's actual complaint (e.g. 'no such column: dog.breed') --
    the same way a human would glance at the error and correct the query.
    Capped at MAX_ATTEMPTS so a persistently broken question doesn't loop forever.

    The attempt number is passed through to the backend so it can raise
    sampling temperature on later tries (see llm/temperature.py) -- a model
    that's deterministically stuck on a wrong answer needs added randomness
    to have any real chance of landing on something different.

    backend.generate_sql can also raise outright (network error, rate limit,
    malformed API response) rather than returning bad SQL -- that's still a
    transient, retryable failure from the pipeline's point of view, not a
    reason to crash the whole request, so it's caught here the same way a
    SQL execution error is.
    """
    prior_error = None
    sql = ""
    known_tables = get_known_tables()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            sql = backend.generate_sql(question, schema_text, prior_error, attempt=attempt)
        except Exception as exc:
            prior_error = f"LLM call failed: {exc}"
            continue

        outcome = execute_sql(sql, known_tables=known_tables)

        if isinstance(outcome, ExecutionResult):
            return PipelineResult(sql=sql, result=outcome, attempts=attempt)

        prior_error = outcome.message

    return PipelineFailure(last_sql=sql, last_error=prior_error, attempts=MAX_ATTEMPTS)
