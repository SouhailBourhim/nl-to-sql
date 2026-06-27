import config
from llm.base import LLMBackend


def get_backend() -> LLMBackend:
    if config.LLM_BACKEND == "api":
        from llm.api_backend import ApiBackend

        return ApiBackend()

    from llm.ollama_backend import OllamaBackend

    return OllamaBackend()
