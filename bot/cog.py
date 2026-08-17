"""TarotSystem cog — all command implementations live here.

Moved from main.py during the package split. Each command stays as a method on
the cog (no behavioural change) but inherits shared helpers via the cog's
self.* references.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import random
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import discord
import requests
from discord.ext import commands

from .ai import NineRouterInterpreter
from .changelog import latest_releases
from .config import (
    AUTHOR_NAME,
    BOT_ADMIN_IDS,
    DEFAULT_LANGUAGE,
    DONATE_KOFI_URL,
    DONATE_MESSAGE,
    DONATE_PAYPAL_URL,
    FIREBASE_AVAILABLE,
    FIREBASE_DATABASE_URL,
    FIREBASE_STORAGE_BUCKET,
    NINE_ROUTER_API_KEY,
    NINE_ROUTER_API_TIMEOUT,
    NINE_ROUTER_ENABLED,
    NINE_ROUTER_MAX_OUTPUT_TOKENS,
    NINE_ROUTER_MODEL,
    NINE_ROUTER_TEMPERATURE,
    NINE_ROUTER_TOP_P,
    JOURNALS_DIR,
    LICENSE_NAME,
    NINE_ROUTER_BASE_URL,
    NINE_ROUTER_ENABLED,
    REPO_URL,
    SAVES_DIR,
    SETTINGS_DIR,
    TAROT_CARDS,
)
from .firebase_service import firebase_service
from .image_gen import CardImageGenerator
from .models import (
    READING_MODES,
    SPREADS,
    CardOrientation,
    ServerSettings,
    SpreadType,
    TarotCard,
    TarotReading,
    UserSettings,
)
from .utils import safe_task as _safe_task
from .views import FeatureView, HelpView

# i18n: pulled from bot_i18n (kept at top of file so `_` is available everywhere
# in the cog body). `bot_i18n` is imported eagerly here — bot/__init__.py wires
# it up before the cog loads.
from bot_i18n import get as _get, get_supported_locales, is_supported, t as _

# NOTE: __version__ is read lazily inside __init__ to avoid a circular import
# (bot/bot.py imports this cog, so importing the package at module-load time
# would race against __init__.py's tail statements that define __version__).


def is_bot_admin(ctx) -> bool:
    """Allow Discord administrators and explicitly configured bot admins."""
    if getattr(getattr(ctx, "author", None), "id", None) in BOT_ADMIN_IDS:
        return True
    permissions = getattr(getattr(ctx, "author", None), "guild_permissions", None)
    return bool(getattr(permissions, "administrator", False))

logger = logging.getLogger(__name__)


class TarotSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Bot version (from bot/__init__.py) — resolved lazily here, not at
        # module load, to dodge the cog <-> package circular import.
        import bot as _bot_pkg
        self.bot_version = getattr(_bot_pkg, "__version__", "0.0.0")
        # Track bot start time for /uptime. Captured at cog construction so
        # /uptime is meaningful even after a hot-reload of the cog itself.
        self._start_time = datetime.now()
        self.user_daily_cooldown = {}
        self.user_weekly_cooldown = {}
        self.user_history = defaultdict(list)
        self.card_statistics = defaultdict(int)
        self.total_readings = 0
        # Reminders: {user_id: {target: {"interval": "daily|weekly|off",
        #                              "next_fire_at": iso8601,
        #                              "paused": bool}}}
        # In-memory mirror of saves/settings/reminders.json
        self.user_reminders: Dict[int, Dict[str, dict]] = defaultdict(dict)
        # Settings cache: avoids re-reading JSON from disk on every command.
        # Pre-populated by _load_user_settings / _load_server_settings.
        self._user_settings_cache: Dict[int, UserSettings] = {}
        self._server_settings_cache: Dict[int, ServerSettings] = {}
        self.ai_interpreter = NineRouterInterpreter(
            enabled=NINE_ROUTER_ENABLED,
            timeout=NINE_ROUTER_API_TIMEOUT,
            max_output_tokens=NINE_ROUTER_MAX_OUTPUT_TOKENS,
            temperature=NINE_ROUTER_TEMPERATURE,
            top_p=NINE_ROUTER_TOP_P,
        )
        self._load_saved_data()
        self._load_user_settings()
        self._load_server_settings()
        self._load_reminders()

        if firebase_service.is_enabled():
            _safe_task(self._sync_to_firebase(), name="initial-firebase-sync")

        # Background reminder dispatcher: scans user_reminders every 60s and
        # sends DM notifications for due reminders. Fire-and-forget so the
        # main loop is not blocked.
        _safe_task(self._reminder_dispatcher_loop(), name="reminder-dispatcher")

    def get_user_settings(self, user_id: int) -> UserSettings:
        """Return cached UserSettings, loading from disk on first access."""
        if user_id not in self._user_settings_cache:
            self._user_settings_cache[user_id] = UserSettings(
                user_id,
                on_change=self.invalidate_user_settings,
            )
        return self._user_settings_cache[user_id]

    def get_server_settings(self, guild_id: int) -> ServerSettings:
        """Return cached ServerSettings, loading from disk on first access."""
        if guild_id not in self._server_settings_cache:
            self._server_settings_cache[guild_id] = ServerSettings(
                guild_id,
                on_change=self.invalidate_server_settings,
            )
        return self._server_settings_cache[guild_id]

    def invalidate_user_settings(self, user_id: int) -> None:
        """Drop a cached user settings entry — call after save() that mutates the file."""
        self._user_settings_cache.pop(user_id, None)

    def invalidate_server_settings(self, guild_id: int) -> None:
        self._server_settings_cache.pop(guild_id, None)

    def _get_settings(self, user_id: int, guild_id: int = None) -> Tuple[UserSettings, Optional[ServerSettings]]:
        user_settings = self.get_user_settings(user_id)
        server_settings = self.get_server_settings(guild_id) if guild_id else None
        return user_settings, server_settings

    @staticmethod
    def _humanize_duration(delta: timedelta) -> str:
        """Render a timedelta as a human-readable string like '2 days, 3h 14m'."""
        total_seconds = int(delta.total_seconds())
        days, rem = divmod(total_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours or days:
            parts.append(f"{hours}h")
        if minutes or hours or days:
            parts.append(f"{minutes}m")
        if not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)

    def _resolve_lang(self, ctx) -> str:
        """Pick the i18n language for the calling context.

        Priority: caller setting > guild Discord locale > default.
        Unknown languages fall back via `is_supported` so we never request a
        translation that the locale loader can't produce.
        """
        try:
            # NOTE: unpack target is named `_server_settings` (not `_`) to
            # avoid shadowing the module-level `t as _` translation function
            # imported at the top of this file.
            user_settings, _server_settings = self._get_settings(
                ctx.author.id,
                ctx.guild.id if ctx.guild else None,
            )
            language = user_settings.get_lang()
        except Exception:
            language = DEFAULT_LANGUAGE
        if not is_supported(language):
            language = DEFAULT_LANGUAGE
        return language

    @staticmethod
    def _split_embed_text(text: str, limit: int = 3600) -> List[str]:
        text = text.strip()
        if not text:
            return []

        chunks = []
        current = ""

        for paragraph in text.split("\n\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue

            if len(paragraph) > limit:
                if current:
                    chunks.append(current.strip())
                    current = ""

                for start in range(0, len(paragraph), limit):
                    chunks.append(paragraph[start:start + limit].strip())
                continue

            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) > limit:
                chunks.append(current.strip())
                current = paragraph
            else:
                current = candidate

        if current:
            chunks.append(current.strip())

        return chunks

    def _ai_interpretation_embeds(self, reading: TarotReading, text: str, model_label: str) -> List[discord.Embed]:
        chunks = self._split_embed_text(text)
        if not chunks:
            return []

        color = reading._spread_info.get("color", 0x7289da)
        embeds = []

        lbl = {
            'title': _("ai_interpretation.title", lang=reading.language),
            'model': _("ai_interpretation.model", lang=reading.language),
            'footer': _("ai_interpretation.footer", lang=reading.language),
        }

        for index, chunk in enumerate(chunks, start=1):
            title = lbl['title']
            if len(chunks) > 1:
                title = f"{title} ({index}/{len(chunks)})"

            embed = discord.Embed(
                title=title,
                description=chunk,
                color=color,
                timestamp=datetime.now()
            )
            embed.set_footer(
                text=f"{lbl['model']}: {model_label} • {lbl['footer']}: {reading.reading_id[:8]}"
            )
            embeds.append(embed)

        return embeds

    async def _send_ai_interpretation(self, ctx, reading: TarotReading):
        if not self.ai_interpreter.is_configured():
            return

        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        if not user_settings.is_ai_enabled():
            return

        lbl = {
            'generating': _("ai_interpretation.generating", lang=reading.language),
        }

        status_msg = await ctx.send(lbl['generating'])
        ai_result = await self.ai_interpreter.generate_interpretation(reading)

        if not ai_result:
            # Silent fallback: 9Router is down or returned garbage. Don't
            # show the user an error banner — just delete the "generating"
            # status and let the local card explanations carry the reading.
            try:
                await status_msg.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException:
                # Fall back to a quiet one-line placeholder so the
                # placeholder doesn't sit there as "still generating...".
                try:
                    await status_msg.edit(
                        content=_("ai_interpretation.silent_skip", lang=reading.language)
                    )
                except (discord.NotFound, discord.HTTPException):
                    pass
            return

        ai_text, was_truncated, model_label = ai_result
        embeds = self._ai_interpretation_embeds(reading, ai_text, model_label)
        if not embeds:
            try:
                await status_msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            return

        # Edit the status message to become the first AI embed to avoid
        # burning follow-up messages on a "generating" placeholder that
        # expires Discord's interaction token (10062) and to stay under
        # the 5 follow-up per-interaction cap (40094).
        try:
            await status_msg.edit(content=None, embed=embeds[0])
        except discord.NotFound:
            # Interaction already expired; user will see no AI response.
            return

        for embed in embeds[1:]:
            try:
                await ctx.send(embed=embed)
            except discord.NotFound:
                # Interaction token expired mid-send; abort gracefully.
                break

        if was_truncated:
            try:
                await ctx.send(_("ai_interpretation.truncated", lang=reading.language))
            except discord.NotFound:
                pass

    @staticmethod
    def _parse_timestamp(value: str) -> Optional[datetime]:
        if not value:
            return None

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except ValueError:
            return None

    def _load_readings_file(self) -> Dict:
        save_path = SAVES_DIR / "readings.json"
        if not save_path.exists():
            return {"readings": [], "statistics": {}}

        with open(save_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _write_readings_file(self, readings: List[Dict]):
        stats = {
            "total_readings": len(readings),
            "daily_readings": sum(1 for reading in readings if reading.get("is_daily")),
            "weekly_readings": sum(1 for reading in readings if reading.get("is_weekly"))
        }

        save_path = SAVES_DIR / "readings.json"
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump({"readings": readings, "statistics": stats}, f, indent=2, ensure_ascii=False)

        self._rebuild_memory_from_readings(readings)

    def _rebuild_memory_from_readings(self, readings: List[Dict]):
        self.user_daily_cooldown.clear()
        self.user_weekly_cooldown.clear()
        self.user_history.clear()
        self.card_statistics.clear()
        self.total_readings = len(readings)

        for reading in readings:
            try:
                user_id = int(reading.get("user_id", 0))
            except (TypeError, ValueError):
                continue

            if not user_id:
                continue

            cards = reading.get("cards", [])
            self.user_history[user_id].append({
                "reading_id": reading.get("reading_id", "N/A"),
                "timestamp": reading.get("timestamp", ""),
                "spread_type": reading.get("spread_type", "unknown"),
                "question": reading.get("question") or "General reading",
                "cards_count": len(cards),
                "language": reading.get("language", "id"),
                "mode": reading.get("mode", "deep")
            })

            for card_info in cards:
                card_name = card_info.get("name")
                if card_name:
                    self.card_statistics[card_name] += 1

            if reading.get("is_daily"):
                timestamp = self._parse_timestamp(reading.get("timestamp", ""))
                if timestamp and (
                    user_id not in self.user_daily_cooldown or
                    timestamp > self.user_daily_cooldown[user_id]
                ):
                    self.user_daily_cooldown[user_id] = timestamp

            if reading.get("is_weekly"):
                timestamp = self._parse_timestamp(reading.get("timestamp", ""))
                if timestamp and (
                    user_id not in self.user_weekly_cooldown or
                    timestamp > self.user_weekly_cooldown[user_id]
                ):
                    self.user_weekly_cooldown[user_id] = timestamp

    def _remember_reading(self, reading: TarotReading):
        self.user_history[reading.user_id].append(reading.to_history_entry())
        self.total_readings += 1

        for card in reading.cards:
            self.card_statistics[card.name] += 1

        if reading.is_daily:
            self.user_daily_cooldown[reading.user_id] = reading.timestamp

        if reading.is_weekly:
            self.user_weekly_cooldown[reading.user_id] = reading.timestamp

    def _count_user_readings(self, user_id: int) -> int:
        """How many readings a user has. Reads from the in-memory index."""
        return len(self.user_history.get(user_id, []))

    def _set_favourite(self, user_id: int, reading_id: str, value: bool = True) -> bool:
        """Toggle the favourite flag on a reading entry. Returns True if a row was updated.

        Mutates both the in-memory history list and the on-disk readings.json
        so the flag survives a bot restart.
        """
        entries = self.user_history.get(user_id, [])
        target = None
        for entry in entries:
            if entry.get("reading_id") == reading_id:
                target = entry
                break
        if target is None:
            return False
        target["favourite"] = bool(value)

        # Persist: rewrite readings.json with the updated entry in-place.
        try:
            data = self._load_readings_file()
            readings = data.get("readings", [])
            for r in readings:
                if r.get("reading_id") == reading_id:
                    r["favourite"] = bool(value)
                    break
            self._write_readings_file(readings)
        except Exception as e:
            logger.error(f"Failed to persist favourite toggle: {e}")
        return True

    def _reset_user_settings(self, user_id: int) -> None:
        """Delete the on-disk settings file for a user and drop the cache entry."""
        path = SETTINGS_DIR / f"user_{user_id}.json"
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.error(f"Failed to delete user settings file {path}: {e}")
        self.invalidate_user_settings(user_id)

    def _load_saved_data(self):
        try:
            data = self._load_readings_file()
            readings = data.get("readings", [])
            self._rebuild_memory_from_readings(readings)
            logger.info(f"Loaded {len(self.user_history)} users' readings")
        except Exception as e:
            logger.error(f"Failed to load saved data: {e}")

    # ------------------------------------------------------------------
    # Reminder storage
    # ------------------------------------------------------------------
    REMINDERS_PATH = SETTINGS_DIR / "reminders.json"
    REMIND_INTERVALS = {"daily", "weekly"}
    REMIND_TARGETS = ("daily_card", "weekly", "tarotdm")
    REMIND_INTERVAL_SECONDS = {"daily": 86400, "weekly": 604800}

    def _load_reminders(self):
        """Populate self.user_reminders from saves/settings/reminders.json."""
        try:
            if not self.REMINDERS_PATH.exists():
                return
            data = json.loads(self.REMINDERS_PATH.read_text("utf-8"))
            for uid_str, targets in data.items():
                try:
                    uid = int(uid_str)
                except ValueError:
                    continue
                if isinstance(targets, dict):
                    self.user_reminders[uid] = {
                        t: v for t, v in targets.items()
                        if t in self.REMIND_TARGETS and isinstance(v, dict)
                    }
            logger.info(
                f"Loaded reminders for {len(self.user_reminders)} users"
            )
        except Exception as e:
            logger.error(f"Failed to load reminders: {e}")

    def _save_reminders(self):
        """Persist self.user_reminders to disk (sync; called on change)."""
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            payload = {str(uid): targets for uid, targets in self.user_reminders.items() if targets}
            self.REMINDERS_PATH.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to save reminders: {e}")

    def _set_reminder(self, user_id: int, target: str, interval: str):
        """Create or replace a reminder. Returns previous interval or None."""
        previous = self.user_reminders.get(user_id, {}).get(target, {}).get("interval")
        now = datetime.now(timezone.utc)
        next_fire = now + timedelta(seconds=self.REMIND_INTERVAL_SECONDS[interval])
        self.user_reminders[user_id][target] = {
            "interval": interval,
            "next_fire_at": next_fire.isoformat(),
            "paused": False,
        }
        self._save_reminders()
        return previous

    def _disable_reminder(self, user_id: int, target: str):
        """Mark a reminder as off (interval=off, paused=True)."""
        self.user_reminders[user_id][target] = {
            "interval": "off",
            "next_fire_at": None,
            "paused": True,
        }
        self._save_reminders()

    def _delete_reminder(self, user_id: int, target: str) -> bool:
        """Remove a reminder entirely. Returns True if something was deleted."""
        bucket = self.user_reminders.get(user_id, {})
        if target in bucket:
            del bucket[target]
            if not bucket:
                self.user_reminders.pop(user_id, None)
            self._save_reminders()
            return True
        return False

    def _pause_reminder(self, user_id: int, target: str) -> bool:
        bucket = self.user_reminders.get(user_id, {})
        if target in bucket:
            bucket[target]["paused"] = True
            self._save_reminders()
            return True
        return False

    def _resume_reminder(self, user_id: int, target: str) -> bool:
        bucket = self.user_reminders.get(user_id, {})
        if target in bucket and bucket[target].get("paused"):
            bucket[target]["paused"] = False
            # Recompute next_fire_at from now so resume is fair.
            interval = bucket[target].get("interval", "off")
            if interval in self.REMIND_INTERVAL_SECONDS:
                bucket[target]["next_fire_at"] = (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=self.REMIND_INTERVAL_SECONDS[interval])
                ).isoformat()
            self._save_reminders()
            return True
        return False

    def _format_next_fire(self, entry: dict, lang: str) -> str:
        """Return human-readable 'next: in X' string for /remind list."""
        if entry.get("interval") == "off" or entry.get("paused"):
            return _("remind.disabled", lang=lang)
        nfa = entry.get("next_fire_at")
        if not nfa:
            return _("remind.disabled", lang=lang)
        try:
            when = datetime.fromisoformat(nfa)
        except ValueError:
            return _("remind.disabled", lang=lang)
        delta = when - datetime.now(timezone.utc)
        if delta.total_seconds() <= 0:
            return _("remind.next_at", lang=lang, time="0s")
        total = int(delta.total_seconds())
        days, rem = divmod(total, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        if days:
            time_str = f"{days}d {hours}h"
        elif hours:
            time_str = f"{hours}h {minutes}m"
        elif minutes:
            time_str = f"{minutes}m {seconds}s"
        else:
            time_str = f"{seconds}s"
        return _("remind.next_at", lang=lang, time=time_str)

    async def _reminder_dispatcher_loop(self):
        """Background loop: every 60s, scan reminders and fire due ones.

        Runs forever until the cog is unloaded. Failures are logged but never
        crash the bot — the next tick will retry.
        """
        # Wait for bot to be ready, but tolerate early shutdown during tests
        # or hot-reload where wait_until_ready may never resolve.
        try:
            await asyncio.wait_for(self.bot.wait_until_ready(), timeout=10)
        except (asyncio.TimeoutError, RuntimeError) as e:
            logger.warning(f"Reminder dispatcher: bot not ready ({e}); retrying on tick")
        logger.info("Reminder dispatcher started")
        while True:
            try:
                if not self.bot.is_ready():
                    await asyncio.sleep(60)
                    continue
                await self._tick_reminders()
            except Exception as e:
                logger.error(f"Reminder dispatcher error: {e}", exc_info=True)
            await asyncio.sleep(60)

    async def _tick_reminders(self):
        """One pass over user_reminders — fire any that are due."""
        now = datetime.now(timezone.utc)
        for uid, targets in list(self.user_reminders.items()):
            for target, entry in list(targets.items()):
                if entry.get("paused") or entry.get("interval") == "off":
                    continue
                nfa = entry.get("next_fire_at")
                if not nfa:
                    continue
                try:
                    when = datetime.fromisoformat(nfa)
                except ValueError:
                    continue
                if when > now:
                    continue
                # Fire it: DM the user, then schedule the next occurrence.
                await self._fire_reminder(uid, target)
                interval = entry.get("interval")
                if interval in self.REMIND_INTERVAL_SECONDS:
                    entry["next_fire_at"] = (
                        now + timedelta(seconds=self.REMIND_INTERVAL_SECONDS[interval])
                    ).isoformat()
                    self._save_reminders()

    async def _fire_reminder(self, user_id: int, target: str):
        """Send a reminder notification to a user (DM preferred, channel fallback)."""
        user_settings = self.get_user_settings(user_id)
        lang = user_settings.get_lang()
        target_label = _("remind.targets." + target, lang=lang, default=target)
        # DM-first
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            if user:
                msg = _("remind.fired_dm", lang=lang, target=target_label)
                await user.send(msg)
                return
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning(f"Failed DM reminder to {user_id}: {e}")
        # Fallback: send to last known guild channel where we saw them.
        # We don't track per-user channel history here; skip silently.
        logger.debug(f"Reminder fired for user {user_id} target {target} (DM failed)")

    def _load_user_settings(self):
        """Pre-populate the user settings cache from disk.

        Previous implementation only counted files. Now we actually load
        them so the first command per user doesn't pay the disk-read cost
        (matters at 10k+ user scale).
        """
        loaded = 0
        skipped = 0
        for path in SETTINGS_DIR.glob("user_*.json"):
            try:
                # Filename format: user_<id>.json
                user_id = int(path.stem.split("_", 1)[1])
            except (IndexError, ValueError):
                skipped += 1
                logger.warning(f"Skipping malformed user settings file: {path.name}")
                continue
            try:
                settings = UserSettings(
                    user_id,
                    on_change=self.invalidate_user_settings,
                )
                self._user_settings_cache[user_id] = settings
                loaded += 1
            except Exception as e:
                skipped += 1
                logger.error(f"Failed to load user settings from {path.name}: {e}")
        logger.info(f"Loaded {loaded} user settings ({skipped} skipped)")

    def _load_server_settings(self):
        """Pre-populate the server settings cache from disk."""
        loaded = 0
        skipped = 0
        for path in SETTINGS_DIR.glob("server_*.json"):
            try:
                guild_id = int(path.stem.split("_", 1)[1])
            except (IndexError, ValueError):
                skipped += 1
                logger.warning(f"Skipping malformed server settings file: {path.name}")
                continue
            try:
                settings = ServerSettings(
                    guild_id,
                    on_change=self.invalidate_server_settings,
                )
                self._server_settings_cache[guild_id] = settings
                loaded += 1
            except Exception as e:
                skipped += 1
                logger.error(f"Failed to load server settings from {path.name}: {e}")
        logger.info(f"Loaded {loaded} server settings ({skipped} skipped)")

    async def _sync_to_firebase(self):
        try:
            if not firebase_service.is_enabled():
                return

            data = self._load_readings_file()
            readings = data.get("readings", [])

            for reading in readings:
                user_id = int(reading.get("user_id", 0))
                if user_id:
                    await firebase_service.async_save_reading(reading, user_id)

            logger.info(f"Synced {len(readings)} readings to Firebase")
        except Exception as e:
            logger.error(f"Failed to sync to Firebase: {e}")

    def draw_cards(self, count: int, allow_reverse: bool = True) -> List[TarotCard]:
        if count > len(TAROT_CARDS):
            count = len(TAROT_CARDS)

        selected = random.sample(TAROT_CARDS, count)
        cards = []

        for card_data in selected:
            orientation = CardOrientation.REVERSED if (
                allow_reverse and random.random() < 0.3
            ) else CardOrientation.UPRIGHT

            card = TarotCard(card_data, orientation)
            cards.append(card)

        return cards

    def can_get_daily(self, user_id: int) -> Tuple[bool, Optional[str]]:
        now = datetime.now()

        if user_id not in self.user_daily_cooldown:
            return True, None

        last_daily = self.user_daily_cooldown[user_id]
        next_available = last_daily + timedelta(hours=22)

        if now >= next_available:
            return True, None

        remaining = next_available - now
        hours = remaining.seconds // 3600
        minutes = (remaining.seconds % 3600) // 60

        return False, f"{hours}h {minutes}m"

    def can_get_weekly(self, user_id: int) -> Tuple[bool, Optional[str]]:
        now = datetime.now()

        if user_id not in self.user_weekly_cooldown:
            return True, None

        last_weekly = self.user_weekly_cooldown[user_id]
        next_available = last_weekly + timedelta(days=6, hours=20)

        if now >= next_available:
            return True, None

        remaining = next_available - now
        days = remaining.days
        hours = remaining.seconds // 3600

        return False, f"{days}d {hours}h"

    async def _handle_reading_reactions(self, ctx, reading_msg, reading: TarotReading):
        def check(reaction, user):
            return (
                user == ctx.author and
                str(reaction.emoji) in ["💾", "📖", "📝"] and
                reaction.message.id == reading_msg.id
            )

        while True:
            try:
                reaction, user = await self.bot.wait_for('reaction_add', timeout=90.0, check=check)
                emoji = str(reaction.emoji)

                if emoji == "💾":
                    await ctx.send(
                        _("tarot.saved_to_history", lang=reading.language, reading_id=reading.reading_id[:8]),
                        delete_after=12
                    )
                elif emoji == "📖":
                    for detail_embed in reading.to_detail_embeds():
                        await ctx.send(embed=detail_embed)
                elif emoji == "📝":
                    await self._journal_prompt(ctx, reading)

                try:
                    await reading_msg.remove_reaction(reaction, user)
                except discord.Forbidden:
                    pass

            except asyncio.TimeoutError:
                try:
                    await reading_msg.clear_reactions()
                except discord.Forbidden:
                    pass
                break

    async def _journal_prompt(self, ctx, reading: TarotReading):
        lbl = {
            'title': _("journal.reflection.title", lang=reading.language),
            'prompt': _("journal.reflection.prompt", lang=reading.language, id=reading.reading_id[:8]),
            'cancel': _("journal.reflection.cancel", lang=reading.language, id=reading.reading_id[:8]),
        }

        embed = discord.Embed(
            title=lbl['title'],
            description=lbl['prompt'],
            color=0x9b59b6
        )
        await ctx.send(embed=embed, delete_after=60)

    # ============================================================
    # COMMANDS WITH DESCRIPTIONS
    # ============================================================

    @commands.hybrid_command(
        name='aimodels',
        description='📋 Lihat daftar model AI yang tersedia melalui 9Router',
        aliases=['models']
    )
    @commands.check(is_bot_admin)
    async def aimodels_command(self, ctx):
        """📋 Show available AI models from 9Router"""
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        lang = user_settings.get_lang()

        try:
            response = requests.get(f"{NINE_ROUTER_BASE_URL}/models", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and 'data' in data:
                    models = [m.get('id') for m in data.get('data', []) if m.get('id')]
                elif isinstance(data, list):
                    models = [m.get('id') for m in data if m.get('id')]
                else:
                    models = []
            else:
                models = []
        except Exception as e:
            logger.warning(f"Could not fetch models: {e}")
            models = []

        if not models:
            models = [
                "kr/claude-sonnet-4.5",
                "kr/claude-sonnet-4.5-thinking",
                "kr/claude-haiku-4.5",
                "kr/deepseek-3.2",
                "kr/qwen3-coder-next",
                "gh/claude-sonnet-4.5",
                "gh/gpt-4o",
                "ds/deepseek-chat",
                "ds/deepseek-reasoner",
                "openrouter/openrouter/free"
            ]

        recommended = ['kr/claude-sonnet-4.5', 'kr/claude-sonnet-4.5-thinking', 'kr/claude-haiku-4.5']

        sorted_models = []
        for rec in recommended:
            if rec in models:
                sorted_models.append(rec)
                models.remove(rec)
        sorted_models.extend(models[:50])

        model_list = "\n".join(sorted_models[:50])
        if len(sorted_models) > 50:
            more = len(sorted_models) - 50
            model_list += _("\n... dan {count} model lainnya", lang=lang, count=more) if lang == 'id' else f"\n... and {more} more models"

        embed = discord.Embed(
            title=_("aimodels.title", lang=lang),
            description=f"```\n{model_list}\n```",
            color=0x9b59b6
        )
        embed.add_field(
            name="📌",
            value=_("aimodel.current", lang=lang, model=user_settings.get_ai_model()),
            inline=False
        )
        embed.add_field(
            name="💡",
            value=_("aimodels.recommended", lang=lang),
            inline=False
        )
        embed.set_footer(text=_("aimodels.footer", lang=lang))
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='aimodel',
        description='🤖 Pilih model AI untuk interpretasi tarot',
        aliases=['setmodel']
    )
    async def aimodel_command(self, ctx, *, model_id: str = None):
        """🤖 Select AI model for tarot interpretations"""
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        lang = user_settings.get_lang()

        if not model_id:
            current_model = user_settings.get_ai_model()
            await ctx.send(
                _("aimodel.current", lang=lang, model=current_model) + "\n\n" +
                _("aimodel.usage", lang=lang)
            )
            return

        if model_id.lower() in ['reset', 'default']:
            user_settings.set_ai_model(NINE_ROUTER_MODEL)
            await ctx.send(_("aimodel.reset", lang=lang, model=NINE_ROUTER_MODEL))
            return

        user_settings.set_ai_model(model_id)
        await ctx.send(_("aimodel.changed", lang=lang, model=model_id))

    @commands.hybrid_command(
        name='tarot',
        description='🔮 Dapatkan reading tarot dengan spread pilihanmu'
    )
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def tarot_command(self, ctx, spread_type: str = None, *, question: str = None):
        user_settings, server_settings = self._get_settings(
            ctx.author.id,
            ctx.guild.id if ctx.guild else None
        )
        language = user_settings.get_lang()
        mode = user_settings.get_mode()

        if spread_type is None:
            await self._show_spread_menu(ctx, language)
            return

        spread_type = spread_type.lower()

        template_mapping = {
            'love': 'love',
            'career': 'career',
            'selfcare': 'selfcare',
            'self-care': 'selfcare',
            'self_care': 'selfcare',
            'shadow': 'shadow',
            'decision': 'decision',
            'weekly': 'weekly'
        }

        if spread_type in template_mapping:
            spread_type = template_mapping[spread_type]

        if spread_type not in SPREADS:
            await ctx.send(_("tarot.spread_unknown", lang=language))
            return

        spread_info = SPREADS[spread_type]

        # Large spreads (>5 cards, e.g. relationship/career/love = 6,
        # celtic = 10) previously asked the user to react ✅ within 30 s to
        # confirm. That prompt made slash commands hang until timeout and
        # surfaced as `HybridCommandError` on every large-spread reading.
        # Skip straight to the draw — cooldowns still gate spam.

        async with ctx.typing():
            cards = self.draw_cards(spread_info["cards"])
            positions = spread_info["positions"].get(language, spread_info["positions"]["id"])

            reading = TarotReading(
                user_id=ctx.author.id,
                spread_type=spread_type,
                cards=cards,
                positions=positions,
                question=question,
                language=language,
                mode=mode
            )

            await reading.async_save_to_history()
            self._remember_reading(reading)

            embed = reading.to_embed()
            embed.set_author(
                name=ctx.author.display_name,
                icon_url=ctx.author.display_avatar.url
            )

            reading_msg = await ctx.send(embed=embed)

            if len(cards) > 1:
                spread_img = reading.generate_spread_image()
                if spread_img:
                    file = discord.File(spread_img, filename="spread_layout.png")
                    await ctx.send("**📊 Spread Layout:**", file=file)

            for detail_embed in reading.to_detail_embeds(page_size=1):
                await ctx.send(embed=detail_embed)

            await self._send_ai_interpretation(ctx, reading)

            if len(cards) <= 5:
                await ctx.send(_("tarot.card_images.header", lang=language))

                for i, (card, position) in enumerate(zip(cards, positions)):
                    img_bytes = CardImageGenerator.generate_card_image(card)
                    if img_bytes:
                        file = discord.File(
                            img_bytes, 
                            filename=f"card_{i+1}_{card.name.replace(' ', '_')}.png"
                        )

                        lbl = {
                            'title': _("tarot.card_images.title", lang=language, number=i+1, name=card.name),
                            'position': _("tarot.card_images.position", lang=language),
                            'orientation': _("tarot.card_images.orientation", lang=language),
                            'keywords': _("tarot.card_images.keywords", lang=language),
                        }

                        card_embed = discord.Embed(
                            title=lbl['title'],
                            description=f"**{lbl['position']}:** {position}\n"
                                      f"**{lbl['orientation']}:** {card.orientation_text}\n"
                                      f"**{lbl['keywords']}:** {', '.join(card.keywords[:3])}",
                            color=embed.color
                        )

                        card_embed.set_image(url=f"attachment://{file.filename}")
                        await ctx.send(embed=card_embed, file=file)
                        await asyncio.sleep(0.5)

            await reading_msg.add_reaction("💾")
            await reading_msg.add_reaction("📖")
            await reading_msg.add_reaction("📝")
            _safe_task(
                self._handle_reading_reactions(ctx, reading_msg, reading),
                name=f"reading-reactions-{reading.reading_id[:8]}",
            )

    async def _show_spread_menu(self, ctx, language: str):
        reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        spread_keys = list(SPREADS.keys())[:10]

        lbl = {
            'title': _("tarot.spread_menu_title", lang=language),
            'description': _("tarot.spread_menu_desc", lang=language),
            'how_to': _("tarot.spread_menu_howto", lang=language),
            'how_to_desc': _("tarot.spread_menu_howto_desc", lang=language),
            'example': _("tarot.spread_menu_example", lang=language),
            'footer': _("tarot.spread_menu_footer", lang=language),
        }

        embed = discord.Embed(
            title=lbl['title'],
            description=lbl['description'],
            color=0x7289da
        )

        spreads_list = []
        for i, (key, info) in enumerate(SPREADS.items()):
            if i >= 10:
                break
            emoji = reactions[i] if i < len(reactions) else "•"
            name = info['name'].get(language, info['name']['id'])
            desc = info['description'].get(language, info['description']['id'])
            spreads_list.append(
                f"{emoji} **{name}** (`{key}`)\n"
                f"*{desc}* - {info['cards']} kartu\n"
            )

        embed.add_field(
            name="Spread Tersedia" if language == "id" else "Available Spreads",
            value="\n".join(spreads_list),
            inline=False
        )

        embed.add_field(
            name=lbl['how_to'],
            value=lbl['how_to_desc'],
            inline=False
        )

        embed.set_footer(text=lbl['example'])

        menu_msg = await ctx.send(embed=embed)

        for i, reaction in enumerate(reactions):
            if i < len(spread_keys):
                await menu_msg.add_reaction(reaction)

        def check(reaction, user):
            return (
                user == ctx.author and
                str(reaction.emoji) in reactions[:len(spread_keys)] and
                reaction.message.id == menu_msg.id
            )

        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)
            selected_index = reactions.index(str(reaction.emoji))
            selected_spread = spread_keys[selected_index]

            try:
                await menu_msg.clear_reactions()
            except discord.Forbidden:
                pass

            embed = discord.Embed(
                title="🔮 Spread Dipilih" if language == "id" else "🔮 Spread Selected",
                description=f"Memulai reading `{selected_spread}` untuk {ctx.author.mention}.",
                color=SPREADS[selected_spread]["color"]
            )
            await menu_msg.edit(embed=embed)

            tarot_command = self.bot.get_command("tarot")
            if tarot_command:
                await ctx.invoke(tarot_command, spread_type=selected_spread)

        except asyncio.TimeoutError:
            try:
                await menu_msg.clear_reactions()
            except discord.Forbidden:
                pass

            lbl = {
                'title': _("tarot.spread_menu.timeout_title", lang=language),
                'description': _("tarot.spread_menu.timeout_desc", lang=language),
            }
            await menu_msg.edit(
                embed=discord.Embed(
                    title=lbl['title'],
                    description=lbl['description'],
                    color=0xe74c3c
                )
            )

    @commands.hybrid_command(
        name='language',
        description='🌐 Ubah bahasa bot (id/en)'
    )
    async def language_command(self, ctx, lang: str = None):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        current_lang = user_settings.get_lang()

        if not lang:
            # No arg given → show current language
            msg = _("language.current", lang=current_lang, lang_code=current_lang)
            await ctx.send(msg)
            return

        lang = lang.lower()
        if not is_supported(lang):
            # Unknown language — show error + help
            supported = get_supported_locales()
            error_msg = _("language.error", lang=current_lang)
            help_msg = _("language.help", lang=current_lang)
            await ctx.send(f"{error_msg}\nSupported: {', '.join(supported)}")
            return

        user_settings.set_language(lang)
        await ctx.send(_("language.set", lang=current_lang, lang_code=lang))

    @commands.hybrid_command(
        name='mode',
        description='🎭 Ubah mode reading (simple/deep/gentle/direct)'
    )
    async def mode_command(self, ctx, mode: str = None):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        lang = user_settings.get_lang()

        if not mode:
            current = user_settings.get_mode()
            await ctx.send(
                _("mode.current", lang=lang, mode=current) + "\n\n" +
                _("mode.available", lang=lang)
            )
            return

        mode = mode.lower()
        if mode not in READING_MODES:
            await ctx.send(
                _("mode.invalid", lang=lang) + "\n" +
                _("mode.help", lang=lang)
            )
            return

        user_settings.set_mode(mode)
        await ctx.send(_("mode.changed", lang=lang, mode=mode))

    @commands.hybrid_command(
        name='aion',
        description='✅ Aktifkan interpretasi AI untuk reading'
    )
    async def ai_on_command(self, ctx):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        lang = user_settings.get_lang()
        user_settings.set_ai_enabled(True)
        await ctx.send(_("ai_toggle.enabled", lang=lang))

    @commands.hybrid_command(
        name='aioff',
        description='⏸️ Nonaktifkan interpretasi AI untuk reading'
    )
    async def ai_off_command(self, ctx):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        lang = user_settings.get_lang()
        user_settings.set_ai_enabled(False)
        await ctx.send(_("ai_toggle.disabled", lang=lang))

    @commands.hybrid_command(
        name='tarotdm',
        description='📩 Dapatkan reading tarot melalui DM (private)'
    )
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def tarotdm_command(self, ctx, spread_type: str = None, *, question: str = None):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        lang = user_settings.get_lang()
        await ctx.send(_("tarotdm.sending", lang=lang))

        if spread_type is None:
            await ctx.author.send("🔮 Silakan pilih spread dengan `!tarotdm [spread] [pertanyaan]`")
            return

        spread_type = spread_type.lower()
        if spread_type not in SPREADS:
            await ctx.author.send(f"❌ Spread tidak dikenal. Spread yang tersedia: `single`, `three`, `celtic`, `relationship`, `career`, `yesno`, `weekly`, `love`, `decision`, `selfcare`, `shadow`")
            return

        user_settings, _server_settings = self._get_settings(ctx.author.id, None)
        language = user_settings.get_lang()
        mode = user_settings.get_mode()

        spread_info = SPREADS[spread_type]
        cards = self.draw_cards(spread_info["cards"])
        positions = spread_info["positions"].get(language, spread_info["positions"]["id"])

        reading = TarotReading(
            user_id=ctx.author.id,
            spread_type=spread_type,
            cards=cards,
            positions=positions,
            question=question,
            language=language,
            mode=mode
        )

        await reading.async_save_to_history()
        self._remember_reading(reading)

        embed = reading.to_embed()
        embed.set_author(
            name=ctx.author.display_name,
            icon_url=ctx.author.display_avatar.url
        )

        await ctx.author.send(embed=embed)

        if len(cards) > 1:
            spread_img = reading.generate_spread_image()
            if spread_img:
                file = discord.File(spread_img, filename="spread_layout.png")
                await ctx.author.send("**📊 Spread Layout:**", file=file)

        for detail_embed in reading.to_detail_embeds(page_size=1):
            await ctx.author.send(embed=detail_embed)

        if self.ai_interpreter.is_configured() and user_settings.is_ai_enabled():
            ai_result = await self.ai_interpreter.generate_interpretation(reading)
            if ai_result:
                ai_text, was_truncated, model_label = ai_result
                await ctx.author.send(f"✨ {model_label}:")
                for embed in self._ai_interpretation_embeds(reading, ai_text, model_label):
                    await ctx.author.send(embed=embed)

        await ctx.send("✅ Reading telah dikirim melalui DM!")

    @commands.hybrid_command(
        name='weekly',
        description='📅 Dapatkan reading mingguan (cooldown 6 hari 20 jam)'
    )
    async def weekly_command(self, ctx):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()
        mode = user_settings.get_mode()

        can_weekly, remaining = self.can_get_weekly(ctx.author.id)

        lbl = {
            'cooldown': _("weekly.cooldown_title", lang=language),
            'cooldown_desc': _("weekly.cooldown_desc", lang=language, time=remaining),
            'title': _("weekly.embed_title", lang=language),
            'footer': _("weekly.embed_footer", lang=language),
        }

        if not can_weekly:
            embed = discord.Embed(
                title=lbl['cooldown'],
                description=lbl['cooldown_desc'],
                color=0xe74c3c
            )
            await ctx.send(embed=embed)
            return

        async with ctx.typing():
            spread_info = SPREADS[SpreadType.WEEKLY.value]
            cards = self.draw_cards(spread_info["cards"])
            positions = spread_info["positions"].get(language, spread_info["positions"]["id"])

            reading = TarotReading(
                user_id=ctx.author.id,
                spread_type=SpreadType.WEEKLY.value,
                cards=cards,
                positions=positions,
                question="Weekly Reading",
                is_weekly=True,
                language=language,
                mode=mode
            )

            await reading.async_save_to_history()
            self._remember_reading(reading)

            embed = discord.Embed(
                title=lbl['title'],
                description=spread_info["description"].get(language, spread_info["description"]["id"]),
                color=spread_info["color"],
                timestamp=datetime.now()
            )

            embed.set_author(
                name=ctx.author.display_name,
                icon_url=ctx.author.display_avatar.url
            )

            for i, (card, position) in enumerate(zip(cards, positions)):
                value = (
                    f"**Makna:** {card.meaning}\n"
                    f"**Kata kunci:** {', '.join(card.keywords[:3])}\n"
                    f"**Orientasi:** {card.orientation_text} {card.orientation_symbol}"
                )
                embed.add_field(
                    name=f"**{i+1}. {position}** - {card.name}",
                    value=value,
                    inline=False
                )

            embed.set_footer(text=f"{lbl['footer']} 6 days 20h")

            await ctx.send(embed=embed)

            for detail_embed in reading.to_detail_embeds(page_size=1):
                await ctx.send(embed=detail_embed)

            await self._send_ai_interpretation(ctx, reading)

    @commands.hybrid_command(
        name='card',
        description='🃏 Lihat detail kartu tarot (bisa cari berdasarkan nama)'
    )
    async def card_command(self, ctx, *, card_name: str = None):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()

        if not card_name:
            card_data = random.choice(TAROT_CARDS)
            card = TarotCard(card_data, random.choice(list(CardOrientation)))
            title = _("daily.random_title", lang=language)
        else:
            found_cards = self._search_cards(card_name)

            if not found_cards:
                await ctx.send(_("card.not_found", lang=language, name=card_name))
                return

            if len(found_cards) > 1:
                await self._show_card_selection(ctx, found_cards, card_name, language)
                return

            card_data = found_cards[0]
            card = TarotCard(card_data)
            title = f"🃏 {card.name}"

        await self._send_card_info(ctx, card, title, language)

    def _search_cards(self, search_term: str) -> List[Dict]:
        search_term = search_term.lower()
        found_cards = []

        for card_data in TAROT_CARDS:
            card_name = card_data['name'].lower()

            if search_term == card_name:
                return [card_data]

            if search_term in card_name:
                found_cards.append(card_data)
            elif any(search_term in str(kw).lower() for kw in card_data.get('keywords', [])):
                found_cards.append(card_data)

        return found_cards

    async def _show_card_selection(self, ctx, cards: List[Dict], search_term: str, language: str):
        selectable_cards = cards[:8]
        reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]

        lbl = {
            'title': _("card_selection.title", lang=language, name=search_term),
            'description': _("card_selection.description", lang=language),
            'footer': _("card_selection.footer", lang=language),
        }

        embed = discord.Embed(
            title=lbl['title'],
            description=lbl['description'],
            color=0xf39c12
        )

        for i, card_data in enumerate(selectable_cards):
            embed.add_field(
                name=f"{reactions[i]} {card_data['name']}",
                value=f"Arcana: {card_data['arcana'].title()} | "
                      f"Keywords: {', '.join(card_data['keywords'][:2])}",
                inline=False
            )

        embed.set_footer(text=lbl['footer'])
        msg = await ctx.send(embed=embed)

        for reaction in reactions[:len(selectable_cards)]:
            await msg.add_reaction(reaction)

        def check(reaction, user):
            return (
                user == ctx.author and
                str(reaction.emoji) in reactions[:len(selectable_cards)] and
                reaction.message.id == msg.id
            )

        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)
            selected_index = reactions.index(str(reaction.emoji))
            selected_card = TarotCard(selectable_cards[selected_index])

            try:
                await msg.clear_reactions()
            except discord.Forbidden:
                pass

            await self._send_card_info(ctx, selected_card, f"🃏 {selected_card.name}", language)

        except asyncio.TimeoutError:
            try:
                await msg.clear_reactions()
            except discord.Forbidden:
                pass

    async def _send_card_info(self, ctx, card: TarotCard, title: str, language: str):
        if card.is_major:
            color = 0xf1c40f
        else:
            color_map = {
                "wands": 0xe67e22,
                "cups": 0x3498db,
                "swords": 0x95a5a6,
                "pentacles": 0x27ae60
            }
            color = color_map.get(card.suit, 0x9b59b6)

        appearances = self.card_statistics.get(card.name, 0)
        lbl = {
            'number': _("card.number", lang=language),
            'arcana': _("card.arcana", lang=language),
            'suit': _("card.suit", lang=language),
            'upright': _("card.upright", lang=language),
            'reversed': _("card.reversed", lang=language),
            'keywords': _("card.keywords", lang=language),
            'appearances': _("card.appearances", lang=language),
            'appearances_desc': _("card.appearances_desc", lang=language, count=appearances),
        }

        embed = discord.Embed(
            title=title,
            description=card.detailed_description or card.description,
            color=color
        )

        embed.add_field(name=lbl['number'], value=f"#{card.number:02d}", inline=True)
        embed.add_field(name=lbl['arcana'], value=card.arcana.title(), inline=True)
        if card.suit:
            embed.add_field(name=lbl['suit'], value=card.suit.title(), inline=True)

        upright_field_index = len(embed.fields)
        embed.add_field(
            name=f"{lbl['upright']} {card.orientation_symbol if not card.is_reversed else ''}",
            value=card.meaning_up,
            inline=False
        )

        reversed_field_index = len(embed.fields)
        embed.add_field(
            name=f"{lbl['reversed']} {'🔄' if card.is_reversed else ''}",
            value=card.meaning_rev,
            inline=False
        )

        embed.add_field(
            name=lbl['keywords'],
            value=", ".join([f"`{kw}`" for kw in card.keywords]),
            inline=False
        )

        if card.name in self.card_statistics:
            count = self.card_statistics[card.name]
            embed.add_field(
                name=f"📊 {lbl['appearances']}",
                value=lbl['appearances_desc'],
                inline=False
            )

        img_bytes = CardImageGenerator.generate_card_image(card)
        if img_bytes:
            filename = f"{card.name.replace(' ', '_').lower()}.png"
            file = discord.File(img_bytes, filename=filename)
            embed.set_image(url=f"attachment://{file.filename}")

            msg = await ctx.send(embed=embed, file=file)
        else:
            msg = await ctx.send(embed=embed)

        await msg.add_reaction("🔄")

        def check(reaction, user):
            return (
                user == ctx.author and
                str(reaction.emoji) == "🔄" and
                reaction.message.id == msg.id
            )

        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)

            new_orientation = (
                CardOrientation.REVERSED 
                if card.orientation == CardOrientation.UPRIGHT 
                else CardOrientation.UPRIGHT
            )

            card.orientation = new_orientation

            embed.set_field_at(
                upright_field_index,
                name=f"{lbl['upright']} {'⬆️' if not card.is_reversed else ''}",
                value=card.meaning_up
            )

            embed.set_field_at(
                reversed_field_index,
                name=f"{lbl['reversed']} {'🔄' if card.is_reversed else ''}",
                value=card.meaning_rev
            )

            img_bytes = CardImageGenerator.generate_card_image(card)
            if img_bytes:
                filename = f"{card.name.replace(' ', '_').lower()}_rev.png"
                file = discord.File(img_bytes, filename=filename)
                embed.set_image(url=f"attachment://{file.filename}")

                await msg.edit(embed=embed)
                try:
                    await msg.remove_reaction("🔄", user)
                except discord.Forbidden:
                    pass

                await ctx.send(_("card.orientation_changed", lang=language, orientation=card.orientation_text), file=file)
            else:
                await msg.edit(embed=embed)
                try:
                    await msg.remove_reaction("🔄", user)
                except discord.Forbidden:
                    pass

        except asyncio.TimeoutError:
            try:
                await msg.clear_reactions()
            except discord.Forbidden:
                pass

    @commands.hybrid_command(
        name='cards',
        description='📋 Lihat daftar kartu tarot (filter berdasarkan kategori)'
    )
    async def cards_command(self, ctx, category: str = None):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()

        if category:
            category = category.lower()

            if category == "major":
                filtered_cards = [c for c in TAROT_CARDS if c['arcana'] == 'major']
                title = _("cards.major", lang=language)
                color = 0xf1c40f
            elif category in ["wands", "cups", "swords", "pentacles"]:
                filtered_cards = [c for c in TAROT_CARDS if c.get('suit') == category]
                title = _("cards." + category, lang=language)
                color = {
                    "wands": 0xe67e22,
                    "cups": 0x3498db,
                    "swords": 0x95a5a6,
                    "pentacles": 0x27ae60
                }[category]
            elif category == "all":
                filtered_cards = TAROT_CARDS
                title = _("cards.all", lang=language)
                color = 0x9b59b6
            else:
                await ctx.send(_("cards.error", lang=language))
                return
        else:
            filtered_cards = TAROT_CARDS
            title = _("cards.overview", lang=language)
            color = 0x7289da

        filtered_cards = sorted(filtered_cards, key=lambda x: (
            x['arcana'] != 'major',
            x.get('suit', ''),
            x['number']
        ))

        cards_per_page = 15
        pages = []

        for i in range(0, len(filtered_cards), cards_per_page):
            page_cards = filtered_cards[i:i + cards_per_page]

            description = ""
            for card in page_cards:
                card_line = f"**{card['name']}**"
                if card['arcana'] == 'minor':
                    card_line += f" ({card['suit'].title()})"
                card_line += f" - #{card['number']:02d}\n"
                description += card_line

            pages.append(description)

        if not pages:
            await ctx.send(_("cards.no_cards", lang=language))
            return

        embed = discord.Embed(
            title=f"{title} ({len(filtered_cards)} cards)",
            description=pages[0],
            color=color
        )

        if len(pages) > 1:
            embed.set_footer(text=_("cards.page_footer", lang=language, current=1, total=len(pages)))

        msg = await ctx.send(embed=embed)

        if len(pages) > 1:
            await msg.add_reaction("⬅️")
            await msg.add_reaction("➡️")

            current_page = 0

            def check(reaction, user):
                return (
                    user == ctx.author and
                    str(reaction.emoji) in ["⬅️", "➡️"] and
                    reaction.message.id == msg.id
                )

            while True:
                try:
                    reaction, user = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)

                    if str(reaction.emoji) == "➡️":
                        current_page = (current_page + 1) % len(pages)
                    else:
                        current_page = (current_page - 1) % len(pages)

                    new_embed = discord.Embed(
                        title=f"{title} ({len(filtered_cards)} cards)",
                        description=pages[current_page],
                        color=color
                    )
                    new_embed.set_footer(text=_("cards.page_footer", lang=language, current=current_page+1, total=len(pages)))

                    await msg.edit(embed=new_embed)
                    try:
                        await msg.remove_reaction(reaction, user)
                    except discord.Forbidden:
                        pass

                except asyncio.TimeoutError:
                    try:
                        await msg.clear_reactions()
                    except discord.Forbidden:
                        break
                    break

    @commands.hybrid_command(
        name='daily',
        description='📅 Dapatkan kartu tarot harianmu (cooldown 22 jam)'
    )
    async def daily_command(self, ctx):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()
        mode = user_settings.get_mode()

        can_daily, remaining = self.can_get_daily(ctx.author.id)

        lbl = {
            'cooldown': _("daily.cooldown_title", lang=language),
            'cooldown_desc': _("daily.cooldown_desc", lang=language, time=remaining),
            'title': _("daily.embed_title", lang=language),
            'advice': _("daily.advice", lang=language),
            'keywords': _("daily.keywords", lang=language),
            'footer': _("daily.embed_footer", lang=language),
            'date': _("daily.date", lang=language),
        }

        if not can_daily:
            embed = discord.Embed(
                title=lbl['cooldown'],
                description=lbl['cooldown_desc'],
                color=0xe74c3c
            )
            await ctx.send(embed=embed)
            return

        async with ctx.typing():
            today = datetime.now().date()
            seed_str = f"{ctx.author.id}{today.strftime('%Y%m%d')}"
            seed = sum(ord(c) for c in seed_str)
            daily_random = random.Random(seed)

            card_data = daily_random.choice(TAROT_CARDS)
            is_reversed = daily_random.choice([True, False])
            card = TarotCard(card_data, 
                           CardOrientation.REVERSED if is_reversed else CardOrientation.UPRIGHT)

            daily_messages = {
                "The Fool": {"id": "Hari untuk awal baru dan petualangan!", "en": "A day for new beginnings and adventures!"},
                "The Magician": {"id": "Kamu memiliki semua alat yang dibutuhkan hari ini.", "en": "You have all the tools you need today."},
                "The High Priestess": {"id": "Percayalah pada intuisimu hari ini.", "en": "Trust your intuition today."},
                "The Empress": {"id": "Rawat dirimu dan orang lain.", "en": "Nurture yourself and others."},
                "The Emperor": {"id": "Ambil kendali dan ciptakan struktur.", "en": "Take charge and create structure."},
                "The Hierophant": {"id": "Cari kebijaksanaan tradisional.", "en": "Seek traditional wisdom."},
                "The Lovers": {"id": "Fokus pada hubungan dan pilihan.", "en": "Focus on relationships and choices."},
                "The Chariot": {"id": "Bergerak maju dengan tekad.", "en": "Move forward with determination."},
                "Strength": {"id": "Temukan keberanian dalam dirimu.", "en": "Find courage within."},
                "The Hermit": {"id": "Waktu untuk introspeksi.", "en": "Time for introspection."},
                "Wheel of Fortune": {"id": "Rangkul perubahan dan peluang.", "en": "Embrace change and opportunity."},
                "Justice": {"id": "Cari keseimbangan dan keadilan.", "en": "Seek balance and fairness."},
                "The Hanged Man": {"id": "Perspektif berbeda diperlukan.", "en": "A different perspective is needed."},
                "Death": {"id": "Lepaskan untuk memberi ruang bagi pertumbuhan baru.", "en": "Let go to make room for new growth."},
                "Temperance": {"id": "Temukan keseimbangan dalam segala hal.", "en": "Find balance in all things."},
                "The Devil": {"id": "Bebaskan diri dari batasan.", "en": "Break free from limitations."},
                "The Tower": {"id": "Perubahan mendadak membawa pertumbuhan.", "en": "Sudden changes bring growth."},
                "The Star": {"id": "Harapan membimbingmu ke depan.", "en": "Hope guides you forward."},
                "The Moon": {"id": "Percayalah pada mimpi dan intuisimu.", "en": "Trust your dreams and intuition."},
                "The Sun": {"id": "Kebahagiaan dan kesuksesan adalah milikmu.", "en": "Joy and success are yours."},
                "Judgement": {"id": "Waktu untuk pembaruan dan kebangkitan.", "en": "Time for renewal and awakening."},
                "The World": {"id": "Penyelesaian dan siklus baru dimulai.", "en": "Completion and new cycles begin."}
            }

            general_messages = {
                "id": [
                    "Renungkan pesan kartu ini sepanjang hari.",
                    "Bawalah kebijaksanaan ini bersamamu hari ini.",
                    "Biarkan kartu ini memandu keputusanmu.",
                    "Meditasi tentang makna kartu ini.",
                    "Energi ini mempengaruhi harimu."
                ],
                "en": [
                    "Reflect on this card's message throughout your day.",
                    "Carry this wisdom with you today.",
                    "Let this card guide your decisions.",
                    "Meditate on this card's meaning.",
                    "This energy influences your day."
                ]
            }

            msg = daily_messages.get(card.name, {})
            message = msg.get(language, general_messages.get(language, general_messages["id"])[0])

            if card.name not in daily_messages:
                message = random.choice(general_messages.get(language, general_messages["id"]))

            color = 0x3498db if not card.is_reversed else 0xe74c3c

            embed = discord.Embed(
                title=f"{lbl['title']}",
                description=f"**{card.name}** ({card.orientation_text})",
                color=color,
                timestamp=datetime.now()
            )

            embed.add_field(
                name=lbl['date'],
                value=today.strftime("%A, %B %d, %Y"),
                inline=True
            )

            embed.add_field(
                name="🧭 Guidance" if language == "en" else "🧭 Panduan",
                value=f"**{message}**\n\n{card.meaning}",
                inline=False
            )

            if card.is_reversed:
                advice = {"id": "⚠️ Ini menandakan pekerjaan batin atau tantangan yang perlu diatasi.", "en": "⚠️ This suggests inner work or challenges to overcome."}
            else:
                advice = {"id": "✨ Energi ini mendukung usahamu hari ini.", "en": "✨ This energy supports your endeavors today."}

            embed.add_field(
                name=lbl['advice'],
                value=advice.get(language, advice["id"]),
                inline=False
            )

            embed.add_field(
                name=lbl['keywords'],
                value=", ".join([f"`{kw}`" for kw in card.keywords[:4]]),
                inline=False
            )

            embed.set_footer(text=f"{lbl['footer']} 22h")

            img_bytes = CardImageGenerator.generate_card_image(card)
            if img_bytes:
                file = discord.File(img_bytes, filename="daily_card.png")
                embed.set_image(url=f"attachment://{file.filename}")
                await ctx.send(embed=embed, file=file)
            else:
                await ctx.send(embed=embed)

            reading = TarotReading(
                user_id=ctx.author.id,
                spread_type="daily",
                cards=[card],
                positions=["Daily Guidance" if language == "en" else "Panduan Harian"],
                question="Daily card draw",
                is_daily=True,
                language=language,
                mode=mode
            )
            await reading.async_save_to_history()
            self._remember_reading(reading)

            for detail_embed in reading.to_detail_embeds(page_size=1):
                await ctx.send(embed=detail_embed)

            await self._send_ai_interpretation(ctx, reading)

    @commands.hybrid_command(
        name='journal',
        description='📝 Kelola jurnal refleksi tarot pribadimu'
    )
    async def journal_command(self, ctx, action: str = None, reading_id: str = None, *, note: str = None):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()

        lbl = {
            'add_error': _("journal.add_error", lang=language),
            'not_found': _("journal.not_found", lang=language),
            'no_entries': _("journal.no_entries", lang=language),
            'title': _("journal.reflection.title", lang=language),
            'entry': _("journal.entry", lang=language),
        }

        if action == "add":
            if not reading_id or not note:
                await ctx.send(lbl['add_error'])
                return

            data = self._load_readings_file()
            found = False
            for reading in data.get("readings", []):
                if reading.get("reading_id", "").startswith(reading_id) or reading.get("reading_id") == reading_id:
                    found = True
                    break

            if not found:
                await ctx.send(lbl['not_found'])
                return

            journal_entry = {
                "reading_id": reading_id,
                "note": note,
                "timestamp": datetime.now().isoformat()
            }

            journal_path = JOURNALS_DIR / f"user_{ctx.author.id}.json"
            journals = []
            if journal_path.exists():
                with open(journal_path, 'r', encoding='utf-8') as f:
                    journals = json.load(f)

            journals.append(journal_entry)

            with open(journal_path, 'w', encoding='utf-8') as f:
                json.dump(journals, f, indent=2, ensure_ascii=False)

            if firebase_service.is_enabled():
                await firebase_service.async_save_journal_entry(ctx.author.id, journal_entry)

            await ctx.send(_("journal.add_success", lang=language, reading_id=reading_id[:8]))
            return

        journal_path = JOURNALS_DIR / f"user_{ctx.author.id}.json"
        entries = []

        if journal_path.exists():
            with open(journal_path, 'r', encoding='utf-8') as f:
                entries = json.load(f)

        if not entries and firebase_service.is_enabled():
            entries = await firebase_service.async_get_journal_entries(ctx.author.id)

        if not entries:
            await ctx.send(lbl['no_entries'])
            return

        entries = sorted(entries, key=lambda x: x.get('timestamp', ''), reverse=True)[:10]

        embed = discord.Embed(
            title=lbl['title'],
            color=0x9b59b6
        )

        for entry in entries:
            try:
                timestamp = self._parse_timestamp(entry.get('timestamp', ''))
                time_str = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else "Unknown"
                embed.add_field(
                    name=f"📖 {entry.get('reading_id', 'N/A')} - {time_str}",
                    value=entry.get('note', '')[:200],
                    inline=False
                )
            except:
                continue

        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='history',
        description='📜 Lihat riwayat reading tarotmu'
    )
    async def history_command(self, ctx, limit: int = 5):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()

        limit = max(1, min(limit, 20))

        readings = self.user_history.get(ctx.author.id, [])

        if not readings and firebase_service.is_enabled():
            firebase_readings = await firebase_service.async_get_user_readings(ctx.author.id, limit)
            if firebase_readings:
                readings = firebase_readings

        total_readings = len(readings)
        lbl = {
            'no_history': _("history.no_history_full", lang=language),
            'no_history_desc': _("history.no_history_desc", lang=language),
            'title': _("history.title", lang=language),
            'q': _("history.question_label", lang=language),
            'cards': _("history.cards", lang=language),
            'footer': _("history.footer", lang=language, shown=limit, total=total_readings),
        }

        if not readings:
            embed = discord.Embed(
                title=lbl['no_history'],
                description=lbl['no_history_desc'],
                color=0x3498db
            )
            await ctx.send(embed=embed)
            return

        readings.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        recent_readings = readings[:limit]

        embed = discord.Embed(
            title=f"{lbl['title']}",
            color=0x9b59b6
        )

        for reading in recent_readings:
            try:
                timestamp = self._parse_timestamp(reading.get('timestamp', ''))
                time_str = timestamp.strftime("%m/%d %H:%M") if timestamp else "Unknown time"

                spread_type = reading.get('spread_type', 'unknown').title()
                question = (reading.get('question') or 'General reading')[:40]
                cards_count = reading.get('cards_count', 1)

                embed.add_field(
                    name=f"{time_str} - {spread_type}",
                    value=(
                        f"**{lbl['q']}:** {question}{'...' if len(question) >= 40 else ''}\n"
                        f"**{lbl['cards']}:** {cards_count} card{'s' if cards_count != 1 else ''}\n"
                        f"**ID:** `{reading.get('reading_id', 'N/A')[:8]}`"
                    ),
                    inline=False
                )
            except:
                continue

        total_count = len(readings)
        embed.set_footer(text=lbl['footer'])

        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='insight',
        description='🔮 Dapatkan wawasan personal dari pola reading tarotmu'
    )
    async def insight_command(self, ctx):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()

        lbl = {
            'more_data': _("insight.more_data", lang=language),
            'more_data_desc': _("insight.more_data_desc", lang=language),
            'title': _("insight.title", lang=language),
            'description': _("insight.description", lang=language),
            'favorite': _("insight.favorite", lang=language),
            'favorite_desc': _("insight.favorite_desc", lang=language),
            'reversed': _("insight.reversed", lang=language),
            'upright': _("insight.upright", lang=language),
            'frequent': _("insight.frequent", lang=language),
            'frequent_desc': _("insight.frequent_desc", lang=language),
            'commitment': _("insight.commitment", lang=language),
            'statistics': _("insight.statistics", lang=language),
            'statistics_desc': _("insight.statistics_desc", lang=language),
            'footer': _("insight.footer", lang=language),
        }

        readings = self.user_history.get(ctx.author.id, [])

        if len(readings) < 3:
            embed = discord.Embed(
                title=lbl['more_data'],
                description=lbl['more_data_desc'],
                color=0xe74c3c
            )
            await ctx.send(embed=embed)
            return

        async with ctx.typing():
            spread_counts = defaultdict(int)
            orientation_counts = {"upright": 0, "reversed": 0}
            card_frequency = defaultdict(int)

            save_path = SAVES_DIR / "readings.json"
            if save_path.exists():
                try:
                    with open(save_path, 'r', encoding='utf-8') as f:
                        all_data = json.load(f)

                    user_readings = [
                        r for r in all_data.get("readings", [])
                        if int(r.get("user_id", 0)) == ctx.author.id
                    ]

                    for reading in user_readings:
                        spread_type = reading.get("spread_type", "unknown")
                        spread_counts[spread_type] += 1

                        for card_info in reading.get("cards", []):
                            card_name = card_info.get("name", "Unknown")
                            card_frequency[card_name] += 1

                            orientation = card_info.get("orientation", "upright")
                            orientation_counts[orientation] += 1

                except Exception as e:
                    logger.error(f"Error loading insights: {e}")

            insights = []

            if spread_counts:
                most_common_spread = max(spread_counts.items(), key=lambda x: x[1])
                insights.append(
                    f"**{lbl['favorite']}:** {lbl['favorite_desc'].format(most_common_spread[0], most_common_spread[1])}"
                )

            total_cards = sum(orientation_counts.values())
            if total_cards > 0:
                reversed_pct = (orientation_counts.get("reversed", 0) / total_cards) * 100
                if reversed_pct > 40:
                    insights.append(lbl['reversed'].format(reversed_pct))
                elif reversed_pct < 20:
                    insights.append(lbl['upright'].format(100 - reversed_pct))

            if card_frequency:
                top_cards = sorted(card_frequency.items(), key=lambda x: x[1], reverse=True)[:3]
                card_names = [card[0] for card in top_cards]
                insights.append(
                    f"**{lbl['frequent']}:** {lbl['frequent_desc'].format(', '.join(card_names))}"
                )

            if len(readings) > 10:
                insights.append(lbl['commitment'])

            embed = discord.Embed(
                title=lbl['title'],
                description=lbl['description'],
                color=0x9b59b6
            )

            for i, insight in enumerate(insights[:4], 1):
                embed.add_field(
                    name=f"Insight #{i}",
                    value=insight,
                    inline=False
                )

            if not insights:
                no_patterns = {"id": "Tidak ada pola yang ditemukan. Teruslah melakukan reading untuk menemukan pola tarot pribadimu.", "en": "No patterns found. Keep getting readings to discover your personal tarot patterns."}
                embed.add_field(
                    name="No Patterns Found" if language == "en" else "Tidak Ada Pola Ditemukan",
                    value=no_patterns.get(language, no_patterns["id"]),
                    inline=False
                )

            embed.add_field(
                name=lbl['statistics'],
                value=lbl['statistics_desc'].format(len(readings), len(spread_counts), len(card_frequency)),
                inline=False
            )

            embed.set_footer(text=lbl['footer'])

            await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='exportdata',
        aliases=['export'],
        description='📦 Ekspor semua data reading tarotmu ke file JSON'
    )
    async def export_data_command(self, ctx):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()

        lbl = {
            'no_data': _("export.no_data", lang=language),
            'exported': _("export.success", lang=language),
            'sent': _("export.sent", lang=language),
            'fallback': _("export.fallback", lang=language),
            'error': _("export.error", lang=language),
        }

        try:
            data = self._load_readings_file()
            user_readings = [
                reading for reading in data.get("readings", [])
                if str(reading.get("user_id")) == str(ctx.author.id)
            ]

            if not user_readings and firebase_service.is_enabled():
                user_readings = await firebase_service.async_get_all_user_readings(ctx.author.id)

            if not user_readings:
                await ctx.send(lbl['no_data'])
                return

            payload = {
                "user_id": str(ctx.author.id),
                "username": str(ctx.author),
                "exported_at": datetime.now().isoformat(),
                "total_readings": len(user_readings),
                "readings": user_readings
            }

            export_bytes = io.BytesIO(json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"))
            file = discord.File(export_bytes, filename=f"tarot_readings_{ctx.author.id}.json")

            try:
                await ctx.author.send(lbl['exported'], file=file)
                await ctx.send(lbl['sent'])
            except discord.Forbidden:
                await ctx.send(lbl['fallback'], file=file)

        except Exception as e:
            logger.error(f"Failed to export user data: {e}", exc_info=True)
            await ctx.send(lbl['error'])

    @commands.hybrid_command(
        name='deletedata',
        aliases=['forgetme'],
        description='🗑️ Hapus semua data reading tarotmu (permanen)'
    )
    async def delete_data_command(self, ctx, confirmation: str = None):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()

        lbl = {
            'confirm': _("delete.confirm", lang=language),
            'no_data': _("delete.no_data", lang=language),
            'deleted': _("delete.deleted", lang=language),
            'error': _("delete.error", lang=language),
        }

        if confirmation != "confirm":
            await ctx.send(lbl['confirm'])
            return

        try:
            data = self._load_readings_file()
            readings = data.get("readings", [])
            remaining_readings = [
                reading for reading in readings
                if str(reading.get("user_id")) != str(ctx.author.id)
            ]

            deleted_count = len(readings) - len(remaining_readings)
            if deleted_count == 0:
                await ctx.send(lbl['no_data'])
                return

            self._write_readings_file(remaining_readings)

            if firebase_service.is_enabled():
                await firebase_service.async_delete_user_data(ctx.author.id)

            journal_path = JOURNALS_DIR / f"user_{ctx.author.id}.json"
            if journal_path.exists():
                journal_path.unlink()

            await ctx.send(lbl['deleted'].format(deleted_count))

        except Exception as e:
            logger.error(f"Failed to delete user data: {e}", exc_info=True)
            await ctx.send(lbl['error'])

    @commands.hybrid_command(
        name='botinfo',
        description='🤖 Lihat informasi tentang bot tarot'
    )
    @commands.check(is_bot_admin)
    async def botinfo_command(self, ctx):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()

        total_users = len(self.user_history)
        total_readings = sum(len(readings) for readings in self.user_history.values())
        most_common = max(self.card_statistics.items(), key=lambda x: x[1]) if self.card_statistics else ("None", 0)

        lbl = {
            'title': _("botinfo.title", lang=language),
            'description': _("botinfo.description", lang=language),
            'statistics': _("botinfo.statistics", lang=language),
            'statistics_desc': _("botinfo.statistics_desc", lang=language),
            'card_stats': _("botinfo.card_stats", lang=language),
            'card_stats_desc': _("botinfo.card_stats_desc", lang=language),
            'technical': _("botinfo.technical", lang=language),
            'technical_desc': _("botinfo.technical_desc", lang=language),
            'features': _("botinfo.features", lang=language),
            'feature_picker': _("botinfo.feature_picker", lang=language),
            'footer': _("botinfo.footer", lang=language),
        }

        embed = discord.Embed(
            title=lbl['title'],
            description=lbl['description'],
            color=0x7289da
        )

        embed.add_field(
            name=lbl['statistics'],
            value=lbl['statistics_desc'].format(total_users, total_readings, len(TAROT_CARDS), len(SPREADS)),
            inline=False
        )

        embed.add_field(
            name=lbl['card_stats'],
            value=lbl['card_stats_desc'].format(
                most_common[0], most_common[1],
                len([c for c in TAROT_CARDS if c['arcana'] == 'major']),
                len([c for c in TAROT_CARDS if c['arcana'] == 'minor'])
            ),
            inline=False
        )

        embed.add_field(
            name=lbl['technical'],
            value=lbl['technical_desc'],
            inline=False
        )

        embed.add_field(
            name=lbl['features'],
            value=lbl['feature_picker'],
            inline=False
        )

        embed.set_footer(text=lbl['footer'])

        view = FeatureView(language, self)
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(
        name='aistatus',
        description='✨ Cek status AI interpreter (9Router)'
    )
    async def ai_status_command(self, ctx):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        lang = user_settings.get_lang()

        if self.ai_interpreter.is_configured():
            status = _("ai_status.enabled", lang=lang)
            mode = "9Router"
            details = _("ai_status.enabled_detail", lang=lang,
                mode=mode,
                model=user_settings.get_ai_model(),
                timeout=self.ai_interpreter.timeout,
                tokens=self.ai_interpreter.max_output_tokens,
            )
            color = 0x2ecc71
        elif not NINE_ROUTER_ENABLED:
            status = _("ai_status.disabled", lang=lang)
            details = _("ai_status.disabled_detail", lang=lang)
            color = 0xf39c12
        else:
            status = _("ai_status.not_configured", lang=lang)
            details = _("ai_status.not_configured_detail", lang=lang)
            color = 0xe74c3c

        user_ai_status = _("ai_status.user_setting_on", lang=lang) if user_settings.is_ai_enabled() else _("ai_status.user_setting_off", lang=lang)

        embed = discord.Embed(
            title=_("ai_status.title", lang=lang),
            color=color
        )
        embed.add_field(name="Status", value=status, inline=False)
        embed.add_field(name="Details", value=details, inline=False)
        embed.add_field(name=_("ai_status.user_enabled", lang=lang, status=user_ai_status), value="", inline=False)
        embed.set_footer(text=_("ai_status.footer", lang=lang))

        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='firebase',
        description='☁️ Cek status koneksi Firebase'
    )
    @commands.check(is_bot_admin)
    async def firebase_status_command(self, ctx):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()

        lbl = {
            'title': _("firebase_status.title", lang=language),
            'connected': _("firebase_status.connected", lang=language),
            'disconnected': _("firebase_status.disconnected", lang=language),
            'enabled': _("firebase_status.enabled", lang=language),
            'disabled': _("firebase_status.disabled", lang=language),
            'sdk': _("firebase_status.sdk", lang=language),
            'status': _("firebase_status.status", lang=language),
            'database': _("firebase_status.database", lang=language),
            'storage': _("firebase_status.storage", lang=language),
            'readings': _("firebase_status.readings", lang=language),
        }

        sdk_status = "Installed ✅" if FIREBASE_AVAILABLE else "Not installed ❌"
        firebase_status = "Enabled" if firebase_service.is_enabled() else "Disabled"

        embed = discord.Embed(
            title=lbl['title'],
            color=0x2ecc71 if firebase_service.is_enabled() else 0xe74c3c
        )

        embed.add_field(
            name="SDK",
            value=lbl['sdk'].format(sdk_status),
            inline=False
        )

        embed.add_field(
            name="Status",
            value=lbl['status'].format(firebase_status),
            inline=False
        )

        if firebase_service.is_enabled():
            embed.add_field(
                name="Database",
                value=lbl['database'].format(FIREBASE_DATABASE_URL or "Not set"),
                inline=False
            )
            embed.add_field(
                name="Storage",
                value=lbl['storage'].format(FIREBASE_STORAGE_BUCKET or "Not set"),
                inline=False
            )

            try:
                docs = firebase_service.db.collection('readings').limit(1000).get()
                total = len(docs)
                embed.add_field(
                    name="Statistics",
                    value=lbl['readings'].format(total),
                    inline=False
                )
            except:
                pass

        embed.set_footer(text="Gunakan !help untuk melihat command lainnya")
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='syncdb',
        description='🔄 Sinkronisasi data lokal ke Firebase (Admin only)'
    )
    @commands.check(is_bot_admin)
    async def sync_db_command(self, ctx):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()

        lbl = {
            'start': _("sync_db.start", lang=language),
            'success': _("sync_db.success", lang=language),
            'error': _("sync_db.error", lang=language),
            'not_enabled': _("sync_db.not_enabled", lang=language),
        }

        if not firebase_service.is_enabled():
            await ctx.send(lbl['not_enabled'])
            return

        await ctx.send(lbl['start'])

        try:
            data = self._load_readings_file()
            readings = data.get("readings", [])

            count = 0
            for reading in readings:
                user_id = int(reading.get("user_id", 0))
                if user_id:
                    if await firebase_service.async_save_reading(reading, user_id):
                        count += 1

            await ctx.send(lbl['success'].format(count))

        except Exception as e:
            await ctx.send(lbl['error'].format(str(e)))

    # ============================================================
    # UTILITY COMMANDS
    # ============================================================

    @commands.hybrid_command(
        name='ping',
        description='🏓 Check bot latency'
    )
    async def ping_command(self, ctx):
        """Measure round-trip latency in milliseconds."""
        # gateway_latency is in seconds → multiply by 1000 for ms.
        latency_ms = round(self.bot.latency * 1000)
        language = ctx.guild.preferred_locale if ctx.guild else DEFAULT_LANGUAGE
        if not is_supported(language):
            language = DEFAULT_LANGUAGE
        await ctx.send(_("ping.latency", lang=language, latency=latency_ms))

    @commands.hybrid_command(
        name='uptime',
        description='⏱️ Show how long the bot has been running'
    )
    async def uptime_command(self, ctx):
        """Report uptime since cog construction."""
        language = self._resolve_lang(ctx)
        delta = datetime.now() - self._start_time
        # Human-friendly uptime string (e.g. "2 days, 3 hours, 14 minutes").
        uptime_str = self._humanize_duration(delta)
        started_at = self._start_time.strftime("%Y-%m-%d %H:%M:%S")
        await ctx.send(_("uptime.value", lang=language, uptime=uptime_str, started_at=started_at))

    @commands.hybrid_command(
        name='profile',
        aliases=['me'],
        description='👤 Lihat profil dan setting tarot kamu'
    )
    async def profile_command(self, ctx):
        """Show the caller's current settings + reading count in a single view."""
        language = self._resolve_lang(ctx)
        # NOTE: must use `_server_settings` (not bare `_`) — see top-of-file
        # import `from bot_i18n import ... t as _`. Shadowing `_` with the
        # second tuple element (`None` in DMs) breaks every `_(...)` call
        # below and produces `TypeError: 'NoneType' object is not callable`.
        user_settings, _server_settings = self._get_settings(
            ctx.author.id,
            ctx.guild.id if ctx.guild else None,
        )
        user_id = ctx.author.id
        total = self._count_user_readings(user_id)
        embed = discord.Embed(
            title=_("profile.title", lang=language),
            color=discord.Color.purple(),
        )
        embed.add_field(
            name=_("profile.user", lang=language),
            value=f"{ctx.author.mention} (`{user_id}`)",
            inline=False,
        )
        embed.add_field(
            name=_("profile.language", lang=language),
            value=user_settings.get_lang(),
            inline=True,
        )
        embed.add_field(
            name=_("profile.mode", lang=language),
            value=user_settings.get_mode(),
            inline=True,
        )
        embed.add_field(
            name=_("profile.ai", lang=language),
            value="✅" if user_settings.is_ai_enabled() else "❌",
            inline=True,
        )
        embed.add_field(
            name=_("profile.ai_model", lang=language),
            value=user_settings.get_ai_model(),
            inline=False,
        )
        embed.add_field(
            name=_("profile.total_readings", lang=language),
            value=str(total),
            inline=True,
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='serverstats',
        description='📊 Lihat statistik tarot di server ini'
    )
    @commands.check(is_bot_admin)
    async def serverstats_command(self, ctx):
        """Per-guild stats. Falls back to bot-wide totals when DM is used."""
        language = self._resolve_lang(ctx)
        guild_name = ctx.guild.name if ctx.guild else "DM"
        embed = discord.Embed(
            title=_("serverstats.title", lang=language),
            color=discord.Color.blue(),
        )
        embed.add_field(
            name=_("serverstats.guild", lang=language),
            value=guild_name,
            inline=False,
        )
        embed.add_field(
            name=_("serverstats.total_readings", lang=language),
            value=str(self.total_readings),
            inline=True,
        )
        if ctx.guild:
            ai_enabled = ctx.guild.id in self._server_settings_cache
            embed.add_field(
                name=_("serverstats.ai_enabled", lang=language),
                value="✅" if ai_enabled else "❌",
                inline=True,
            )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='feedback',
        description='📝 Kirim feedback ke developer'
    )
    async def feedback_command(self, ctx, message: str = None):
        """Send a feedback message to the bot owner via webhook / DM.

        The bot owner receives feedback in two ways:
        1. Logged to `tarot_bot.log` at INFO level (always works).
        2. Forwarded via the existing Discord webhook if configured.
        """
        language = self._resolve_lang(ctx)
        if not message or len(message) > 500:
            await ctx.send(_("feedback.error", lang=language))
            return

        author = f"{ctx.author.name}#{ctx.author.discriminator} ({ctx.author.id})"
        guild_name = f"{ctx.guild.name} ({ctx.guild.id})" if ctx.guild else "DM"
        logger.info(
            f"[FEEDBACK] from {author} in {guild_name}: {message}"
        )
        await ctx.send(_("feedback.success", lang=language))

    @commands.hybrid_command(
        name='reset_settings',
        description='♻️ Reset setting user ke default'
    )
    async def reset_settings_command(self, ctx):
        """Reset the caller's user settings to defaults after confirmation."""
        language = self._resolve_lang(ctx)
        await ctx.send(_("reset_settings.confirm", lang=language))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            reply = await self.bot.wait_for(
                "message",
                check=check,
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            await ctx.send(_("reset_settings.cancelled", lang=language))
            return

        if reply.content.strip().lower() != "yes":
            await ctx.send(_("reset_settings.cancelled", lang=language))
            return

        self._reset_user_settings(ctx.author.id)
        await ctx.send(_("reset_settings.done", lang=language))

    @commands.hybrid_command(
        name='invite',
        description='🔗 Dapatkan link invite bot ke server lain'
    )
    async def invite_command(self, ctx):
        """Generate an OAuth2 invite URL for this bot."""
        language = self._resolve_lang(ctx)
        permissions = discord.Permissions(
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_messages=True,
            read_message_history=True,
            add_reactions=True,
            use_external_emojis=True,
        )
        url = discord.utils.oauth_url(
            self.bot.user.id,
            permissions=permissions,
        )
        embed = discord.Embed(
            title=_("invite.title", lang=language),
            description=f"{_('invite.desc', lang=language)}\n{url}",
            color=discord.Color.gold(),
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='favourite',
        aliases=['favorite', 'fav'],
        description='⭐ Toggle favourite flag pada sebuah reading'
    )
    async def favourite_command(self, ctx, reading_id: str = None):
        """Toggle favourite on a reading by ID, or list favourites when no ID is given."""
        language = self._resolve_lang(ctx)
        entries = self.user_history.get(ctx.author.id, [])

        if reading_id is None:
            # No ID → list favourites.
            favs = [e for e in entries if e.get("favourite")]
            if not favs:
                await ctx.send(_("favourite.no_history", lang=language))
                return
            lines = [
                f"⭐ `{e['reading_id']}` — {e.get('spread_type', '?')} — {e.get('question') or '(no question)'}"
                for e in favs[-10:]  # cap at 10 to stay under Discord's 2000-char limit
            ]
            await ctx.send("\n".join(lines))
            return

        # Determine toggle: if already favourite, unfavourite it; otherwise mark as favourite.
        current = next((e for e in entries if e.get("reading_id") == reading_id), None)
        if current is None:
            await ctx.send(_("favourite.not_found", lang=language, reading_id=reading_id))
            return

        new_value = not bool(current.get("favourite", False))
        updated = self._set_favourite(ctx.author.id, reading_id, value=new_value)
        if not updated:
            await ctx.send(_("favourite.not_found", lang=language, reading_id=reading_id))
            return

        if new_value:
            await ctx.send(_("favourite.favourited", lang=language, reading_id=reading_id))
        else:
            await ctx.send(_("favourite.unfavourited", lang=language, reading_id=reading_id))

    @commands.hybrid_command(
        name='remind',
        description='⏰ Set / list / pause periodic tarot reminders (daily, weekly)'
    )
    async def remind_command(self, ctx, action: str = None, target: str = None, interval: str = None):
        """Manage periodic reminders for daily card, weekly reading, etc.

        Usage:
          /remind set daily_card daily
          /remind set weekly weekly
          /remind set tarotdm off
          /remind list
          /remind delete daily_card
          /remind pause daily_card
          /remind resume daily_card
        """
        language = self._resolve_lang(ctx)
        user_id = ctx.author.id

        # Default: show list when no args
        if action is None:
            action = "list"

        action = action.lower()
        if action == "list":
            entries = self.user_reminders.get(user_id, {})
            if not entries:
                await ctx.send(_("remind.list_empty", lang=language))
                return
            lines = []
            for t in self.REMIND_TARGETS:
                e = entries.get(t)
                if not e:
                    continue
                next_str = self._format_next_fire(e, language)
                target_label = _("remind.targets." + t, lang=language, default=t)
                lines.append(
                    _("remind.list_entry", lang=language,
                      target=target_label, interval=e.get("interval", "off"),
                      next=next_str)
                )
            embed = discord.Embed(
                title=_("remind.list_title", lang=language),
                description="\n".join(lines) if lines else _("remind.list_empty", lang=language),
                color=discord.Color.purple(),
            )
            await ctx.send(embed=embed)
            return

        if action in ("set", "delete", "pause", "resume"):
            if target is None:
                await ctx.send(_("remind.target_invalid", lang=language))
                return
            target = target.lower()
            if target not in self.REMIND_TARGETS:
                await ctx.send(_("remind.target_invalid", lang=language))
                return

            if action == "set":
                interval_key = (interval or "").lower()
                if interval_key == "off":
                    self._disable_reminder(user_id, target)
                    await ctx.send(_("remind.off", lang=language, target=target))
                    return
                if interval_key not in self.REMIND_INTERVALS:
                    await ctx.send(_("remind.interval_invalid", lang=language))
                    return
                previous = self._set_reminder(user_id, target, interval_key)
                target_label = _("remind.targets." + target, lang=language, default=target)
                if previous and previous != interval_key:
                    await ctx.send(_("remind.replaced", lang=language,
                                     target=target_label, previous=previous))
                elif interval_key == "weekly":
                    await ctx.send(_("remind.set_weekly", lang=language, target=target_label))
                else:
                    await ctx.send(_("remind.set_daily", lang=language, target=target_label))
                return

            if action == "delete":
                ok = self._delete_reminder(user_id, target)
                if ok:
                    await ctx.send(_("remind.deleted", lang=language, target=target))
                else:
                    await ctx.send(_("remind.not_found", lang=language))
                return

            if action == "pause":
                ok = self._pause_reminder(user_id, target)
                if ok:
                    await ctx.send(_("remind.paused", lang=language, target=target))
                else:
                    await ctx.send(_("remind.not_found", lang=language))
                return

            if action == "resume":
                ok = self._resume_reminder(user_id, target)
                if ok:
                    await ctx.send(_("remind.resumed", lang=language, target=target))
                else:
                    await ctx.send(_("remind.not_found", lang=language))
                return

        # Unknown action
        await ctx.send(_("remind.interval_invalid", lang=language))

    @commands.hybrid_command(
        name='donate',
        description='☕ Dukung pengembangan bot via Ko-fi / PayPal'
    )
    async def donate_command(self, ctx):
        """Show donation links to support the bot's development."""
        language = self._resolve_lang(ctx)
        author_name = getattr(ctx.author, "display_name", str(ctx.author))

        description = _("donate.desc", lang=language)
        # Operator-set custom message takes precedence; otherwise use i18n default
        custom = (DONATE_MESSAGE or "").strip()
        if custom:
            description = f"{description}\n\n{custom}"
        else:
            description = f"{description}\n\n{_('donate.custom_message', lang=language)}"

        embed = discord.Embed(
            title=_("donate.title", lang=language),
            description=description,
            color=0xff5e7e,  # warm pink/coral
        )
        embed.set_footer(text=_("donate.footer", lang=language))

        # Build link buttons (only if URL is configured)
        view = None
        buttons = []
        if DONATE_KOFI_URL:
            buttons.append(
                discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label=_("donate.ko_fi", lang=language),
                    url=DONATE_KOFI_URL,
                    emoji="☕",
                )
            )
        if DONATE_PAYPAL_URL:
            buttons.append(
                discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label=_("donate.paypal", lang=language),
                    url=DONATE_PAYPAL_URL,
                )
            )
        if buttons:
            view = discord.ui.View(timeout=None)
            for btn in buttons:
                view.add_item(btn)

        if view is not None:
            await ctx.send(embed=embed, view=view)
        else:
            await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='source',
        description='📦 Lihat repositori, versi, dan lisensi bot'
    )
    async def source_command(self, ctx):
        """Show project metadata: repo URL, version, license, dependencies."""
        language = self._resolve_lang(ctx)

        # Best-effort runtime info — degrade gracefully if a lib can't be queried.
        try:
            py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        except Exception:
            py_version = "?"
        try:
            dpy_version = discord.__version__
        except Exception:
            dpy_version = "?"
        try:
            total_locales = len(get_supported_locales())
        except Exception:
            total_locales = 5  # known count; safest static fallback

        embed = discord.Embed(
            title=_("source.title", lang=language),
            color=0x24292e,  # GitHub dark
        )

        # Repo / version / license / author — kept as separate fields so each
        # value sits on its own line (avoids markdown link ambiguity).
        embed.add_field(
            name="\u200b",
            value=_("source.repo", lang=language, url=REPO_URL),
            inline=False,
        )
        embed.add_field(
            name="\u200b",
            value=_("source.version", lang=language, version=self.bot_version),
            inline=False,
        )
        embed.add_field(
            name="\u200b",
            value=_("source.license", lang=language, license=LICENSE_NAME),
            inline=False,
        )
        embed.add_field(
            name="\u200b",
            value=_("source.author", lang=language, author=AUTHOR_NAME),
            inline=False,
        )

        # Stack: bundled into one field so it reads as a tidy block.
        stack_lines = [
            _("source.python", lang=language, version=py_version),
            _("source.discord_py", lang=language, version=dpy_version),
            _("source.total_locales", lang=language, n=total_locales),
        ]
        embed.add_field(
            name=_("source.stack", lang=language),
            value="\n".join(stack_lines),
            inline=False,
        )

        embed.set_footer(text=_("source.footer", lang=language))
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='changelog',
        description='📜 Lihat catatan perubahan & update terbaru'
    )
    async def changelog_command(self, ctx, count: int = 3):
        """Show the most recent releases from CHANGELOG.md.

        Usage:
          /changelog        → 3 latest releases (default)
          /changelog 5      → 5 latest releases
        """
        language = self._resolve_lang(ctx)

        # Bound the requested count so a curious user can't dump the whole
        # changelog into one embed (Discord caps at 25 fields, each at 1024
        # chars). 1..5 keeps a single embed readable.
        count = max(1, min(int(count), 5))

        try:
            releases = latest_releases(count)
        except Exception as e:
            logger.warning(f"changelog: failed to parse ({e})")
            releases = []

        if not releases:
            await ctx.send(_("changelog.no_changelog", lang=language))
            return

        embed = discord.Embed(
            title=_("changelog.title", lang=language),
            color=0x9b59b6,
        )

        for release in releases:
            version = release.get("version", "?")
            date = release.get("date")
            date_line = (
                _("changelog.release_date", lang=language, date=date)
                if date else
                _("changelog.no_date", lang=language)
            )
            header = f"**v{version}** — {date_line}"

            # Build bullet list grouped by section. Each section becomes its
            # own embed field so Discord lays them out cleanly.
            sections = release.get("sections") or {}
            if not sections:
                embed.add_field(name=header, value="_(no details)_", inline=False)
                continue

            # Pre-compute section labels for the locale.
            section_labels = {
                name: _("changelog.section_" + name.lower(), lang=language)
                for name in ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")
                if name in sections
            }
            # Keep canonical ordering: Added → Changed → Deprecated → Removed → Fixed → Security
            canonical_order = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")
            ordered_names = [n for n in canonical_order if n in sections]

            # First field: header + first section, so the version is anchored
            # to its content even on mobile.
            first_name = ordered_names[0]
            first_label = section_labels[first_name]
            first_bullets = "\n".join(f"• {b}" for b in sections[first_name])
            embed.add_field(
                name=header,
                value=f"**{first_label}**\n{first_bullets}",
                inline=False,
            )

            for name in ordered_names[1:]:
                label = section_labels[name]
                bullets = "\n".join(f"• {b}" for b in sections[name])
                embed.add_field(name=label, value=bullets, inline=False)

        # Point users at the source file so they can read the full thing.
        try:
            changelog_relpath = "CHANGELOG.md"  # relative to project root
        except Exception:
            changelog_relpath = "CHANGELOG.md"
        embed.set_footer(
            text=_("changelog.footer", lang=language, path=changelog_relpath)
        )

        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='resetcooldown',
        description='⏱️ [Admin] Reset cooldown user atau seluruh server'
    )
    @commands.check(is_bot_admin)
    async def resetcooldown_command(
        self,
        ctx,
        target: Optional[discord.Member] = None,
        kind: str = "all",
    ):
        """Admin: reset daily/weekly cooldowns for a user (or the whole server).

        Usage:
          /resetcooldown @user          → reset all (daily + weekly)
          /resetcooldown @user daily    → reset only daily
          /resetcooldown (no target)    → reset cooldowns of all users in this server
        """
        language = self._resolve_lang(ctx)
        kind_key = (kind or "all").lower()
        if kind_key not in ("daily", "weekly", "all"):
            await ctx.send(_("resetcooldown.invalid_kind", lang=language))
            return

        embed = discord.Embed(
            title=_("resetcooldown.title", lang=language),
            color=0x2ecc71,  # green for "go ahead"
        )

        admin_id = ctx.author.id

        if target is None:
            # Server-wide reset. Only iterate users who actually have cooldowns.
            user_ids = set(self.user_daily_cooldown.keys()) | set(self.user_weekly_cooldown.keys())
            if not user_ids:
                await ctx.send(_("resetcooldown.no_cooldown_server", lang=language))
                return
            cleared = 0
            if kind_key in ("daily", "all"):
                for uid in user_ids:
                    if uid in self.user_daily_cooldown:
                        self.user_daily_cooldown.pop(uid, None)
                        cleared += 1
            if kind_key in ("weekly", "all"):
                for uid in user_ids:
                    if uid in self.user_weekly_cooldown:
                        self.user_weekly_cooldown.pop(uid, None)
                        cleared += 1
            embed.description = _("resetcooldown.desc_server", lang=language, count=cleared)
            embed.color = 0x2ecc71
        else:
            # Single-user reset.
            mention = getattr(target, "mention", f"<@{target.id}>")
            had_any = (
                target.id in self.user_daily_cooldown
                or target.id in self.user_weekly_cooldown
            )
            if not had_any:
                embed.description = _("resetcooldown.no_cooldown_user",
                                       lang=language, user_id=target.id)
                embed.color = 0x95a5a6  # neutral grey
                await ctx.send(embed=embed)
                return
            if kind_key in ("daily", "all"):
                self.user_daily_cooldown.pop(target.id, None)
            if kind_key in ("weekly", "all"):
                self.user_weekly_cooldown.pop(target.id, None)
            if kind_key == "all":
                desc_key = "resetcooldown.desc_user_all"
            elif kind_key == "daily":
                desc_key = "resetcooldown.desc_user_daily"
            else:
                desc_key = "resetcooldown.desc_user_weekly"
            embed.description = _(desc_key, lang=language,
                                   user_id=target.id, mention=mention)

        admin_name = getattr(ctx.author, "display_name", str(ctx.author))
        embed.set_footer(
            text=_("resetcooldown.footer", lang=language,
                   admin=admin_name, kind=kind_key)
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='share',
        description='🔗 Bagikan reading tarot-mu ke user lain via DM atau ke channel ini',
    )
    async def share_command(
        self,
        ctx,
        reading_id: str,
        target_user: Optional[discord.Member] = None,
    ):
        """Share a tarot reading as a rich embed.

        Usage:
          /share <reading_id>                    → share to current channel
          /share <reading_id> @user              → send DM to that user
        """
        language = self._resolve_lang(ctx)
        entries = self.user_history.get(ctx.author.id, [])

        if not entries:
            await ctx.send(_("share.no_history", lang=language))
            return

        # Match reading_id prefix (allow short IDs like history command shows)
        match = None
        for e in entries:
            eid = str(e.get("reading_id", ""))
            if eid == reading_id or eid.startswith(reading_id):
                match = e
                break

        if match is None:
            await ctx.send(_("share.invalid_id", lang=language, reading_id=reading_id))
            return

        # Build embed
        spread_key = match.get("spread_type", "single")
        spread_info = SPREADS.get(spread_key, {})
        spread_name = spread_info.get("name", {}).get(language) or \
            spread_info.get("name", {}).get("en") or spread_key.title()

        question = match.get("question")
        ts = self._parse_timestamp(match.get("timestamp", "")) if hasattr(self, "_parse_timestamp") else None
        time_str = ts.strftime("%Y-%m-%d %H:%M") if ts else "?"

        # Try to recover card names from disk (history entries strip card details)
        # so the share embed shows actual cards instead of just a count.
        cards_text = self._cards_summary_for_reading(ctx.author.id, match)
        cards_count = match.get("cards_count", 1)

        author_name = getattr(ctx.author, "display_name", str(ctx.author))
        embed = discord.Embed(
            title=_("share.embed_title", lang=language, author=author_name),
            color=spread_info.get("color", 0x9b59b6),
            timestamp=ts or datetime.now(),
        )
        if question:
            embed.description = _("share.embed_question", lang=language, question=question)
        else:
            embed.description = _("share.embed_question_none", lang=language)
        embed.add_field(
            name="Spread",
            value=spread_name,
            inline=True,
        )
        embed.add_field(
            name=f"Cards ({cards_count})",
            value=cards_text if cards_text else f"{cards_count} card(s)",
            inline=False,
        )
        embed.add_field(
            name="Time",
            value=time_str,
            inline=True,
        )
        embed.add_field(
            name="ID",
            value=f"`{match.get('reading_id', 'N/A')}`",
            inline=False,
        )
        embed.set_footer(
            text=_("share.embed_footer", lang=language,
                   reading_id_short=match.get("reading_id", "")[:8])
        )

        # Decide destination: DM target_user if given, else current channel
        if target_user is not None and not isinstance(target_user, discord.Member):
            # Slash command may pass a User rather than Member when invoked in DMs.
            # Treat both the same.
            target_user = target_user
        if target_user is not None:
            try:
                await target_user.send(embed=embed)
                await ctx.send(_("share.dm_sent", lang=language, user_id=target_user.id))
                return
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warning(f"Failed DM share to {target_user.id}: {e}")
                await ctx.send(_("share.dm_failed", lang=language))
                # Still fall through to posting in channel as a courtesy.
        await ctx.send(embed=embed)
        if target_user is not None:
            # already notified about DM failure above; nothing more to do
            return
        await ctx.send(_("share.channel_sent", lang=language))

    def _cards_summary_for_reading(self, user_id: int, entry: dict) -> str:
        """Look up card names for a history entry.

        History entries only store cards_count (not the full card list).
        For /share we want the actual names, so we peek into the on-disk
        readings.json. Returns a comma-separated list, capped to fit embed.
        """
        reading_id = entry.get("reading_id")
        if not reading_id:
            return ""
        try:
            path = SAVES_DIR / "readings.json"
            if not path.exists():
                return ""
            data = json.loads(path.read_text("utf-8"))
        except Exception:
            return ""
        for r in data.get("readings", []):
            if str(r.get("reading_id")) == str(reading_id):
                cards = r.get("cards") or []
                names = []
                for c in cards:
                    name = c.get("name", "?") if isinstance(c, dict) else str(c)
                    orient = c.get("orientation", "upright") if isinstance(c, dict) else "upright"
                    if orient == "reversed":
                        name += " (R)"
                    names.append(name)
                # Cap at 5 cards in summary to keep embed readable
                if len(names) > 5:
                    shown = ", ".join(names[:5])
                    return f"{shown}, +{len(names) - 5} more"
                return ", ".join(names) if names else ""
        return ""

    @commands.hybrid_command(
        name='help',
        description='🔮 Tampilkan menu bantuan lengkap'
    )
    async def help_command(self, ctx):
        user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
        language = user_settings.get_lang()

        lbl = {
            'title': _("help.title", lang=language),
            'description': _("help.description", lang=language),
            'picker': _("help.category_picker", lang=language),
            'examples': _("help.examples", lang=language),
            'examples_desc': _("help.examples_desc", lang=language),
            'tips': _("help.tips", lang=language),
            'tips_desc': _("help.tips_desc", lang=language),
            'footer': _("help.footer_text", lang=language),
        }

        embed = discord.Embed(
            title=lbl['title'],
            description=lbl['description'],
            color=0x9b59b6
        )

        embed.add_field(
            name='📚',
            value=lbl['picker'],
            inline=False
        )

        embed.add_field(
            name=lbl['examples'],
            value=lbl['examples_desc'],
            inline=False
        )

        embed.add_field(
            name=lbl['tips'],
            value=lbl['tips_desc'],
            inline=False
        )

        embed.set_footer(text=lbl['footer'])

        view = HelpView(language, self)
        await ctx.send(embed=embed, view=view)

    async def cog_command_error(self, ctx, error):
        """Slash/app-command error handler scoped to this cog.

        Prefix command errors still go through ``bot.bot.on_command_error``;
        this method catches ``HybridCommandError`` and the wrapped
        ``CheckFailure`` raised when ``@commands.check(is_bot_admin)`` denies
        a slash invocation. Without it, the user just sees ``HybridCommand
        Error: ... CheckFailure: ...``.
        """
        # Unwrap HybridCommandError to the underlying cause.
        original = error
        if isinstance(error, commands.HybridCommandError):
            original = getattr(error, "original", error)

        if isinstance(original, commands.CheckFailure):
            author_id = getattr(getattr(ctx, "author", None), "id", None)
            try:
                language = self._resolve_lang(ctx)
            except Exception:
                language = "id"
            try:
                msg = _("errors.admin_only", lang=language, user_id=author_id)
            except Exception:
                msg = (
                    f"🔒 Command ini hanya untuk admin bot. "
                    f"User ID kamu: `{author_id}`."
                )
            try:
                await ctx.send(msg, ephemeral=True)
            except (discord.NotFound, discord.HTTPException):
                try:
                    await ctx.send(msg)
                except discord.NotFound:
                    pass
            return

        # Anything else: re-raise so the global handler can decide.
        raise error
