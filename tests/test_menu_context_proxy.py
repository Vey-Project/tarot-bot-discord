"""Regression test for reaction-menu reading output routing.

A slash /tarot spread menu consumes the interaction's initial response. If the
selected reading reuses that same Context, every later output goes through the
interaction follow-up webhook and can fail with 40094/10003. The selected
reading must instead use the ordinary channel message API.

Run: ./venv/bin/python tests/test_menu_context_proxy.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.cog import _ChannelContextProxy  # noqa: E402


class FakeTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return "channel-message"

    def typing(self):
        return FakeTyping()


class FakeContext:
    def __init__(self, channel):
        self.channel = channel
        self.author = object()
        self.guild = object()
        self.interaction = object()


async def main():
    channel = FakeChannel()
    original = FakeContext(channel)
    proxy = _ChannelContextProxy(original)

    assert proxy.author is original.author
    assert proxy.guild is original.guild
    assert proxy.interaction is original.interaction
    assert await proxy.send("reading output", delete_after=12) == "channel-message"
    assert channel.sent == [(("reading output",), {"delete_after": 12})]

    async with proxy.typing():
        pass

    print("OK: menu-selected reading routes sends through the normal channel")


asyncio.run(main())
