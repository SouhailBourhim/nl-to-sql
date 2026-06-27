import requests

import config
from llm.base import LLMBackend
from llm.extract import extract_sql
from pipeline.prompt_templates import build_explain_chat_messages, build_sql_chat_messages


class ApiBackend(LLMBackend):
    """Calls any OpenAI-compatible chat-completion API (default: NVIDIA's
    hosted endpoint at https://build.nvidia.com). Unlike the local Ollama
    backend, this talks to a general-purpose instruct model over chat
    messages rather than sqlcoder's raw-completion template -- see
    pipeline/prompt_templates.py for the chat-specific prompts.
    """

    def __init__(
        self,
        base_url: str = config.API_BASE_URL,
        api_key: str | None = config.API_KEY,
        model: str = config.API_MODEL,
    ):
        if not api_key:
            raise ValueError("API_KEY must be set in .env to use ApiBackend")
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def _chat(self, messages: list[dict]) -> str:
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 1024,
                "stream": False,
            },
            # Same lesson learned with the Ollama backend: a hosted LLM call
            # can occasionally run well past a minute (model cold-starts,
            # free-tier throttling, etc.), so a generous margin avoids
            # treating a slow-but-successful call as a hard failure.
            timeout=120,
        )
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Chat completion response was not valid JSON: {response.text}") from exc

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"Chat completion response had no 'choices': {data}")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise RuntimeError(f"Chat completion response had no usable message content: {data}")

        return content

    def generate_sql(self, question: str, schema_text: str, prior_error: str | None = None) -> str:
        messages = build_sql_chat_messages(question, schema_text, prior_error)
        raw = self._chat(messages)
        return extract_sql(raw)

    def explain_result(self, question: str, sql: str, columns: list[str], rows: list[tuple]) -> str:
        messages = build_explain_chat_messages(question, sql, columns, rows)
        return self._chat(messages).strip()
