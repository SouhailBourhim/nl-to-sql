import re

import requests

import config
from llm.base import LLMBackend
from pipeline.prompt_templates import build_explain_prompt, build_sql_prompt


class OllamaBackend(LLMBackend):
    """Calls a model running locally under Ollama via its plain HTTP API.

    Ollama runs as a background daemon (started by `ollama serve`, or
    automatically by the desktop app) and exposes /api/generate for
    single-shot, non-chat completions — which is what a base/fine-tuned
    model like sqlcoder expects, as opposed to a chat-formatted model.
    """

    def __init__(self, host: str = config.OLLAMA_HOST, model: str = config.OLLAMA_MODEL):
        self.host = host
        self.model = model

    def _generate(self, prompt: str) -> str:
        response = requests.post(
            f"{self.host}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                # A low (not zero) temperature: testing showed temperature=0
                # (greedy decoding) can deterministically get stuck repeating
                # the same wrong answer on every retry. A little randomness
                # keeps answers close to the model's best guess while still
                # giving the retry loop in pipeline/retry.py a real second
                # chance to land on a different, hopefully correct, output.
                "options": {"temperature": 0.3},
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["response"]

    def generate_sql(self, question: str, schema_text: str, prior_error: str | None = None) -> str:
        prompt = build_sql_prompt(question, schema_text, prior_error)
        raw = self._generate(prompt)
        return _extract_sql(raw)

    def explain_result(self, question: str, sql: str, columns: list[str], rows: list[tuple]) -> str:
        prompt = build_explain_prompt(question, sql, columns, rows)
        raw = self._generate(prompt)
        # sqlcoder is fine-tuned for writing SQL, not prose -- it tends to
        # echo a markdown header (e.g. "### Answer #:") before the actual
        # sentence, a habit picked up from its SQL-prompt training data.
        return re.sub(r"^#+.*\n+", "", raw.strip()).strip()


def _extract_sql(raw_text: str) -> str:
    """sqlcoder sometimes wraps its answer in a ```sql fence, and since our
    template ends with the literal token "[SQL]", the model often echoes it
    back (either as an opening tag before its answer or a closing [/SQL]
    after it) -- strip whichever markers show up so we're left with bare SQL."""
    text = raw_text.strip()
    fence_match = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1)
    text = re.sub(r"\[/?SQL\]", "", text, flags=re.IGNORECASE)
    return text.strip().rstrip(";").strip()
