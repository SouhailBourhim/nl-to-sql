from abc import ABC, abstractmethod
from typing import Optional


class LLMBackend(ABC):
    """The seam between the pipeline and whatever model actually generates SQL/text.

    Everything downstream (sql_generator, retry, explainer) talks to this
    interface only. Swapping sqlcoder-via-Ollama for a hosted API model later
    means writing one new class here — nothing else in the codebase changes.
    """

    @abstractmethod
    def generate_sql(self, question: str, schema_text: str, prior_error: Optional[str] = None) -> str:
        ...

    @abstractmethod
    def explain_result(self, question: str, sql: str, columns: list[str], rows: list[tuple]) -> str:
        ...
