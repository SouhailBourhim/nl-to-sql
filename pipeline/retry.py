from dataclasses import dataclass

from llm.base import LLMBackend
from pipeline.executor import ExecutionError, ExecutionResult, execute_sql

MAX_ATTEMPTS = 3


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
    """
    prior_error = None
    sql = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        sql = backend.generate_sql(question, schema_text, prior_error)
        outcome = execute_sql(sql)

        if isinstance(outcome, ExecutionResult):
            return PipelineResult(sql=sql, result=outcome, attempts=attempt)

        prior_error = outcome.message

    return PipelineFailure(last_sql=sql, last_error=prior_error, attempts=MAX_ATTEMPTS)
