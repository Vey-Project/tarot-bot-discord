"""9Router retry policy: deterministic 4xx must not be retried, and the
server's own error body must reach the log.

Live in bot.log: 35 x "400 Client Error" and 7 x "503 Service Unavailable",
each followed by the same number of retries. A 4xx is a contract violation —
the identical request fails identically every time, so retrying only burns
10 x 120s of blocking I/O.

Run: PYTHONPATH=. python3 tests/test_ai_retry_policy.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

import bot.ai as ai_module  # noqa: E402
from bot.ai import NonRetryableAIError, is_retryable_status  # noqa: E402


def test_status_classification():
    for status in (400, 401, 403, 404, 422):
        assert not is_retryable_status(status), status
    for status in (408, 409, 429, 500, 502, 503, 504):
        assert is_retryable_status(status), status


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.ok = 200 <= status_code < 400

    def json(self):
        import json
        return json.loads(self.text)


def _patch_post(monkey_status, monkey_text):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json))
        return FakeResponse(monkey_status, monkey_text)

    return calls, fake_post


def test_400_raises_non_retryable_and_logs_body():
    interp = ai_module.NineRouterInterpreter(
        enabled=True, max_retries=10, retry_backoff=0.0
    )
    interp.api_key = "sk-test"
    interp.default_model = "test-model"
    interp.enabled = True

    calls, fake_post = _patch_post(400, '{"error":{"message":"context length exceeded"}}')
    original = ai_module.requests.post
    ai_module.requests.post = fake_post
    try:
        try:
            interp._call_9router_sync("prompt", "test-model")
        except NonRetryableAIError as exc:
            assert "400" in str(exc)
            assert "context length exceeded" in str(exc), str(exc)
        else:
            raise AssertionError("400 did not raise NonRetryableAIError")
    finally:
        ai_module.requests.post = original

    assert len(calls) == 1, calls


def test_503_raises_retryable_http_error():
    interp = ai_module.NineRouterInterpreter(
        enabled=True, max_retries=10, retry_backoff=0.0
    )
    interp.api_key = "sk-test"
    interp.enabled = True

    calls, fake_post = _patch_post(503, "<html>upstream down</html>")
    original = ai_module.requests.post
    ai_module.requests.post = fake_post
    try:
        try:
            interp._call_9router_sync("prompt", "test-model")
        except requests.HTTPError as exc:
            assert "503" in str(exc)
            assert not isinstance(exc, NonRetryableAIError)
        else:
            raise AssertionError("503 did not raise HTTPError")
    finally:
        ai_module.requests.post = original

    assert len(calls) == 1, calls


def test_200_path_still_works():
    interp = ai_module.NineRouterInterpreter(enabled=True, max_retries=3, retry_backoff=0.0)
    interp.api_key = "sk-test"
    interp.enabled = True

    body = '{"choices":[{"message":{"content":"  Reflective text.  "}}],"usage":{"total_tokens":10}}'
    calls, fake_post = _patch_post(200, body)
    original = ai_module.requests.post
    ai_module.requests.post = fake_post
    try:
        text, truncated = interp._call_9router_sync("prompt", "test-model")
    finally:
        ai_module.requests.post = original
    assert text == "Reflective text.", repr(text)
    assert truncated is False


for fn in list(globals().values()):
    if callable(fn) and getattr(fn, "__name__", "").startswith("test_"):
        fn()

print("OK: 9Router 4xx is not retried and the error body reaches the log")