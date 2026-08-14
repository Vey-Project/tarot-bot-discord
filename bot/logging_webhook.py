"""Discord webhook logging handler.

Sends WARNING+ log records to a Discord webhook URL with throttling so a log
spike doesn't flood the channel. Uses a daemon thread + queue so emit() never
blocks the asyncio event loop.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime

import requests


class DiscordWebhookHandler(logging.Handler):
    """Logging handler that sends WARNING+ messages to a Discord webhook."""

    def __init__(
        self,
        webhook_url: str,
        level: int = logging.WARNING,
        throttle_seconds: float = 5.0,
    ):
        super().__init__(level)
        self.webhook_url = webhook_url
        self.throttle_seconds = throttle_seconds
        self._log_queue: queue.Queue = queue.Queue()
        self._last_sent: float = 0.0
        self._lock = threading.Lock()
        self._worker_thread = threading.Thread(
            target=self._worker,
            daemon=True,
            name="webhook-logger",
        )
        self._worker_thread.start()

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self._log_queue.put_nowait(msg)
        except Exception:
            self.handleError(record)

    def _worker(self):
        while True:
            try:
                msg = self._log_queue.get(timeout=1)
                self._send_with_throttle(msg)
            except queue.Empty:
                continue
            except Exception:
                # Never let the worker thread die from an unexpected error.
                self.handleError(None) if False else None  # noqa: E701

    def _send_with_throttle(self, msg: str):
        with self._lock:
            now = time.time()
            elapsed = now - self._last_sent
            if elapsed < self.throttle_seconds:
                time.sleep(self.throttle_seconds - elapsed)
            self._last_sent = time.time()

        if len(msg) > 1900:
            msg = msg[:1900] + "\n…[truncated]"

        try:
            payload = {
                "content": None,
                "embeds": [{
                    "title": "📋 Bot Log",
                    "description": f"```{msg}```",
                    "color": 0xe74c3c,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }],
            }
            requests.post(self.webhook_url, json=payload, timeout=5)
        except Exception:
            pass


def setup_logging(
    log_file: str = "tarot_bot.log",
    webhook_url: str = None,
    level_name: str = "WARNING",
    throttle_seconds: float = 5.0,
):
    """Configure root logging with rotating file + optional webhook handler.

    Returns the webhook handler instance (or ``None`` if no URL was given) so
    callers can shut it down at exit.
    """
    from logging.handlers import RotatingFileHandler

    level = getattr(logging, level_name.upper(), logging.WARNING)

    handlers = [
        RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB per file
            backupCount=5,
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ]

    webhook_handler = None
    if webhook_url:
        webhook_handler = DiscordWebhookHandler(
            webhook_url=webhook_url,
            level=level,
            throttle_seconds=throttle_seconds,
        )
        handlers.append(webhook_handler)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,  # re-configure if basicConfig was already called
    )
    return webhook_handler