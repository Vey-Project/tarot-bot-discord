"""Discord webhook logging handler.

Sends log records at level >= DISCORD_LOG_LEVEL to a Discord channel via
incoming webhook. Throttled per-record to avoid rate-limit spam.

Why a custom handler and not just an aiohttp post from the cog:
- Single source of truth for log routing.
- Throttling belongs to the transport, not the call sites.
- Records redact user IDs / channel IDs / tokens before posting.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

try:
    import aiohttp
    _AIOHTTP = True
except ImportError:
    _AIOHTTP = False


_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")
_DISCORD_EPOCH = 1420070400000
_DISCORD_ID_RE = re.compile(r"\b(\d{17,20})\b")


def _redact(text: str) -> str:
    text = _TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    # Snowflake IDs are 17-20 digit numbers. Mask the middle to keep readability.
    def _mask(m):
        s = m.group(0)
        return f"{s[:4]}…{s[-4:]}"
    text = _DISCORD_ID_RE.sub(_mask, text)
    return text[:1800]  # Discord content limit


class DiscordWebhookHandler(logging.Handler):
    """Async-friendly webhook log handler.

    Posts one Discord message per record (subject to throttle). Records are
    queued and sent by a background task that the caller starts with .start()
    and stops with .stop().
    """

    def __init__(self, webhook_url: str, level: int = logging.WARNING,
                 throttle_seconds: float = 5.0, queue_max: int = 100):
        super().__init__(level=level)
        if not webhook_url:
            raise ValueError("webhook_url is required")
        self.webhook_url = webhook_url
        self.throttle = throttle_seconds
        self.queue: asyncio.Queue = None  # type: ignore
        self._queue_max = queue_max
        self._last_sent = 0.0
        self._task: Optional[asyncio.Task] = None
        self._session: Optional["aiohttp.ClientSession"] = None
        self._dropped = 0

    def _format(self, record: logging.LogRecord) -> str:
        ts = self.format(record) if self.formatter else record.getMessage()
        return _redact(ts)

    def emit(self, record: logging.LogRecord):
        if self.queue is None or self.queue.full():
            self._dropped += 1
            return
        try:
            self.queue.put_nowait(record)
        except Exception:
            self._dropped += 1

    async def start(self):
        if not _AIOHTTP:
            logging.getLogger(__name__).warning("aiohttp not installed; webhook handler disabled")
            return
        self.queue = asyncio.Queue(maxsize=self._queue_max)
        self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._pump(), name="discord-log-pump")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self._session:
            try:
                await self._session.close()
            except Exception:
                pass
        if self._dropped:
            logging.getLogger(__name__).warning(f"Discord log: dropped {self._dropped} records (queue full)")

    async def _pump(self):
        while True:
            try:
                record = await self.queue.get()
            except asyncio.CancelledError:
                return
            try:
                await self._send(record)
            except Exception as e:
                # Never let logging crash the bot.
                logging.getLogger(__name__).debug(f"discord log send failed: {e}")

    async def _send(self, record: logging.LogRecord):
        import time
        now = time.monotonic()
        wait = self.throttle - (now - self._last_sent)
        if wait > 0:
            await asyncio.sleep(wait)
        body = self._format(record)
        payload = {"content": f"```{record.levelname} {record.name}\n{body}```"}
        try:
            async with self._session.post(self.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status >= 400:
                    logging.getLogger(__name__).debug(f"webhook {resp.status}")
                else:
                    self._last_sent = time.monotonic()
        except Exception as e:
            logging.getLogger(__name__).debug(f"webhook post: {e}")
