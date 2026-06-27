from llm.base import LLMBackend


class FakeLLMBackend(LLMBackend):
    """Canned-response stand-in for a real model, so pipeline tests don't
    depend on Ollama/NVIDIA being reachable. One SQL string per retry attempt
    (the last one repeats if more attempts happen than responses provided),
    so a test can script "wrong query, then a fixed one" to exercise the
    retry loop deterministically.
    """

    def __init__(self, sql_responses: list[str], explanation: str = "canned explanation"):
        self.sql_responses = sql_responses
        self.explanation = explanation
        self.generate_calls: list[dict] = []

    def generate_sql(
        self, question: str, schema_text: str, prior_error: str | None = None, attempt: int = 1
    ) -> str:
        self.generate_calls.append(
            {"question": question, "prior_error": prior_error, "attempt": attempt}
        )
        index = min(attempt - 1, len(self.sql_responses) - 1)
        return self.sql_responses[index]

    def explain_result(self, question: str, sql: str, columns: list[str], rows: list[tuple]) -> str:
        return self.explanation
