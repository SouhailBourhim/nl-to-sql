import config
from llm.base import LLMBackend

_VALID_BACKENDS = ("ollama", "api")


def get_backend() -> LLMBackend:
    if config.LLM_BACKEND not in _VALID_BACKENDS:
        raise ValueError(
            f"Unknown LLM_BACKEND '{config.LLM_BACKEND}'; expected one of {_VALID_BACKENDS}"
        )

    if config.LLM_BACKEND == "api":
        from llm.api_backend import ApiBackend

        return ApiBackend()

    from llm.ollama_backend import OllamaBackend

    return OllamaBackend()
