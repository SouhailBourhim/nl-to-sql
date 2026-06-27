import os

from dotenv import load_dotenv

load_dotenv()


DATABASE_URL = os.environ["DATABASE_URL"]
LLM_BACKEND = os.environ.get("LLM_BACKEND", "ollama")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "sqlcoder")
# Generic OpenAI-compatible chat-completion backend. Defaults point at
# NVIDIA's hosted API (https://build.nvidia.com), but any OpenAI-compatible
# endpoint (OpenAI itself, Together, etc.) works by overriding API_BASE_URL.
API_BASE_URL = os.environ.get("API_BASE_URL", "https://integrate.api.nvidia.com/v1")
API_KEY = os.environ.get("API_KEY")
API_MODEL = os.environ.get("API_MODEL", "meta/llama-3.1-70b-instruct")
MAX_RESULT_ROWS = int(os.environ.get("MAX_RESULT_ROWS", "200"))
