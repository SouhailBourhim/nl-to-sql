from llm.base import LLMBackend
from pipeline.executor import ExecutionResult


def explain(backend: LLMBackend, question: str, sql: str, result: ExecutionResult) -> str:
    return backend.explain_result(question, sql, result.columns, result.rows)
