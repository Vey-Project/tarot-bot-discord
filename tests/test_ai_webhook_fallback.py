"""The AI reading must reach the user even when the interaction token died.

Inside a slash command, ctx.send() returns a WebhookMessage bound to the
interaction token. Discord invalidates that token after 15 minutes; a slow
9Router (timeout 120s x up to 10 retries) outlives it, and editing the
placeholder then fails with 401/50027. Fall back to a channel send, which
authenticates as the bot and has no expiry.

Run: PYTHONPATH=. python3 tests/test_ai_webhook_fallback.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import discord  # noqa: E402

from bot.cog import TarotSystem  # noqa: E402


class StubResponse:
    def __init__(self, status, reason):
        self.status, self.reason = status, reason

    def __str__(self):
        return f"{self.status} {self.reason}"


def http_error(status, reason, code, message):
    return discord.HTTPException(
        StubResponse(status, reason), {"code": code, "message": message}
    )


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return "channel-message"


def not_found(code=10008, message="Unknown Message"):
    """Build the exception discord.py actually raises for a 404.

    discord.py maps HTTP status -> exception subclass, so 10008 arrives as a
    ``discord.NotFound``, not a bare ``HTTPException``. Constructing a bare
    HTTPException with code 10008 would test a shape the library never
    produces.
    """
    return discord.NotFound(StubResponse(404, "Not Found"), {"code": code, "message": message})


class FakeStatusMessage:
    def __init__(self, edit_error=None):
        self.edit_error = edit_error
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        if self.edit_error:
            raise self.edit_error

    async def delete(self):
        return None


class FakeSettings:
    def is_ai_enabled(self):
        return True


class FakeInterpreter:
    def is_configured(self):
        return True

    async def generate_interpretation(self, reading):
        return ("Insight text that is long enough to matter.", False, "9Router (m)")


def static_interpreter(text=None, configured=True):
    """An interpreter whose generate_interpretation is a real coroutine."""

    class _Interpreter:
        def is_configured(self):
            return configured

        async def generate_interpretation(self, reading):
            if text is None:            # 9Router down -> silent fallback
                return None
            return (text, False, "9Router (m)")

    return _Interpreter()


def build(status_msg, channel):
    cog = TarotSystem.__new__(TarotSystem)          # skip __init__: no live bot
    cog.ai_interpreter = FakeInterpreter()
    cog._get_settings = lambda *a, **k: (FakeSettings(), FakeSettings())

    class Ctx:
        def __init__(self):
            self.channel = channel
            self.interaction = object()
            self.guild = None
            self.author = type("A", (), {"id": 1})()
            self.followups = []

        async def send(self, *args, **kwargs):
            self.followups.append((args, kwargs))
            return status_msg

    reading = type("R", (), {})()
    reading.user_id = 1
    reading.language = "id"
    reading.reading_id = "abcdef123456"
    reading._spread_info = {"color": 0x7289da}
    return cog, Ctx(), reading


async def main():
    # 1. Healthy edit: the placeholder is edited, nothing goes to the channel.
    channel = FakeChannel()
    status = FakeStatusMessage()
    cog, ctx, reading = build(status, channel)
    await TarotSystem._send_ai_interpretation(cog, ctx, reading)
    assert len(status.edits) == 1, status.edits
    assert channel.sent == [], channel.sent

    # 2. 50027: the token expired mid-call. The reading must still land.
    channel = FakeChannel()
    status = FakeStatusMessage(
        edit_error=http_error(401, "Unauthorized", 50027, "Invalid Webhook Token")
    )
    cog, ctx, reading = build(status, channel)
    await TarotSystem._send_ai_interpretation(cog, ctx, reading)
    assert len(channel.sent) == 1, f"AI reading lost: {channel.sent}"
    assert channel.sent[0][1]["embed"].description.startswith("Insight text")

    # 3. Multi-chunk AI text + 50027: every chunk goes to the channel, and
    #    nothing leaks back through the dead interaction token.
    channel = FakeChannel()
    long_text = "\n\n".join(f"Paragraph {i}. " + "x" * 200 for i in range(30))
    status = FakeStatusMessage(
        edit_error=http_error(401, "Unauthorized", 50027, "Invalid Webhook Token")
    )
    cog, ctx, reading = build(status, channel)
    cog.ai_interpreter = static_interpreter(text=long_text)
    await TarotSystem._send_ai_interpretation(cog, ctx, reading)
    # 30 x ~215-char paragraphs exceed the 3600-char chunk limit, so the
    # reading is split. First embed -> channel (edit died), rest -> channel.
    assert len(channel.sent) >= 2, f"expected chunked delivery, got {len(channel.sent)}"
    assert channel.sent[0][1]["embed"].description.startswith("Paragraph 0.")
    assert all(kwargs.get("embeds") for _, kwargs in channel.sent[1:]), "rest not batched"
    assert len(ctx.followups) == 1, "placeholder was re-sent through the dead token"

    # 4. 10008: the message was deleted. Nothing is sent anywhere — the
    #    existing behaviour, and it must not change.
    channel = FakeChannel()
    status = FakeStatusMessage(edit_error=not_found())
    cog, ctx, reading = build(status, channel)
    await TarotSystem._send_ai_interpretation(cog, ctx, reading)
    assert channel.sent == [], channel.sent

    # 5. 9Router down: placeholder is deleted, no channel send, no error.
    channel = FakeChannel()
    status = FakeStatusMessage()
    cog, ctx, reading = build(status, channel)
    cog.ai_interpreter = static_interpreter(text=None)
    await TarotSystem._send_ai_interpretation(cog, ctx, reading)
    assert channel.sent == [], channel.sent

    print("OK: AI reading falls back to a channel send when the interaction token expired")


asyncio.run(main())