"""Transient Firestore transport errors must be retried, then given up on.

bot.log holds 101 failures: 98 x ConnectionResetError(10054) and 3 x
Read timed out, each a 120s stall followed by a 40-line traceback. A reset
peer or a dropped route is worth another attempt; repeating it 200 times a
day is not.

Run: PYTHONPATH=. python3 tests/test_firebase_retry.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.firebase_service import FirebaseService  # noqa: E402


def bare_service():
    """A FirebaseService with no Firestore client and a known-clean breaker."""
    svc = object.__new__(FirebaseService)  # bypass the singleton __new__
    svc.enabled = False
    svc.db = None
    svc.bucket = None
    svc._quota_exhausted = False
    svc._transport_down = False
    svc._consecutive_transport_failures = 0
    svc._retry_backoff = 0.0
    svc._max_transport_retries = 3
    return svc


class Transient(Exception):
    pass


def test_transient_error_is_retried_then_succeeds():
    svc = bare_service()
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise Transient("Connection aborted. ConnectionResetError(10054)")
        return "written"

    started = time.monotonic()
    assert svc._retrying(flaky) == "written"
    assert attempts["n"] == 3, attempts
    assert time.monotonic() - started < 1.0
    assert svc._consecutive_transport_failures == 0


def test_non_transient_error_propagates_on_first_attempt():
    svc = bare_service()
    attempts = {"n": 0}

    def broken():
        attempts["n"] += 1
        raise ValueError("bad document field")

    try:
        svc._retrying(broken)
    except ValueError as exc:
        assert "bad document field" in str(exc)
    else:
        raise AssertionError("ValueError was swallowed by the retry wrapper")
    assert attempts["n"] == 1, attempts


def test_breaker_opens_after_five_consecutive_failures():
    svc = bare_service()
    svc._max_transport_retries = 2
    attempts = {"n": 0}

    def always_down():
        attempts["n"] += 1
        raise Transient("Read timed out. (read timeout=120)")

    for _ in range(2):
        try:
            svc._retrying(always_down)
        except Transient:
            pass
    # 2 rounds x 2 retries = 4 consecutive failures; the 5th opens the breaker.
    assert not svc._transport_down, "breaker opened too early"

    try:
        svc._retrying(always_down)
    except Transient:
        pass
    assert svc._transport_down, "breaker never opened"
    assert attempts["n"] == 5, attempts

    # Once open, further calls must not even reach the network.
    before = attempts["n"]
    try:
        svc._retrying(always_down)
    except Exception:
        pass
    assert attempts["n"] == before, "retry wrapper ran after the breaker opened"


for fn in list(globals().values()):
    if callable(fn) and getattr(fn, "__name__", "").startswith("test_"):
        fn()

print("OK: transient Firestore errors retry, permanent ones don't, breaker holds")