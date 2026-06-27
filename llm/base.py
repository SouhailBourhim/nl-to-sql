from abc import ABC, abstractmethod
from typing import Optional


class LLMBackend(ABC):
    """The seam between the pipeline and whatever model actually generates SQL/text.

    Everything downstream (sql_generator, retry, explainer) talks to this
    interface only. Swapping sqlcoder-via-Ollama for a hosted API model later
    means writing one new class here — nothing else in the codebase changes.
    """

    @abstractmethod
    def generate_sql(
        self, question: str, schema_text: str, prior_error: Optional[str] = None, attempt: int = 1
    ) -> str:
        """`attempt` is the 1-based retry count from pipeline/retry.py. Backends
        may use it to raise sampling temperature on later attempts -- testing
        showed a model can get deterministically stuck repeating the same wrong
        answer otherwise, making retries pointless without some added variance.
        """
        ...

    @abstractmethod
    def explain_result(self, question: str, sql: str, columns: list[str], rows: list[tuple]) -> str:
        ...
