from unittest.mock import MagicMock, patch

from llm.api_backend import ApiBackend


def _response(status_code: int, json_body: dict | None = None, headers: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.json.return_value = json_body or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_chat_retries_on_429_then_succeeds():
    backend = ApiBackend(api_key="fake-key")
    success = _response(200, {"choices": [{"message": {"content": "SELECT 1"}}]})
    rate_limited = _response(429, headers={"Retry-After": "0"})

    with patch("llm.api_backend.requests.post", side_effect=[rate_limited, success]) as mock_post, \
         patch("llm.api_backend.time.sleep") as mock_sleep:
        result = backend._chat([{"role": "user", "content": "hi"}])

    assert result == "SELECT 1"
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once()


def test_chat_raises_after_exhausting_rate_limit_retries():
    backend = ApiBackend(api_key="fake-key")
    rate_limited = _response(429)

    with patch("llm.api_backend.requests.post", return_value=rate_limited), \
         patch("llm.api_backend.time.sleep"):
        try:
            backend._chat([{"role": "user", "content": "hi"}])
            assert False, "expected an exception after exhausting retries"
        except Exception:
            pass


def test_chat_does_not_retry_on_non_429_error():
    backend = ApiBackend(api_key="fake-key")
    server_error = _response(500)

    with patch("llm.api_backend.requests.post", return_value=server_error) as mock_post:
        try:
            backend._chat([{"role": "user", "content": "hi"}])
            assert False, "expected an exception"
        except Exception:
            pass

    assert mock_post.call_count == 1
