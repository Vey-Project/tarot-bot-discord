"""Discord bot wiring: intents, instance, setup_hook, event handlers, run()."""

from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands

from .cog import TarotSystem
from .config import (
    GEMINI_MODEL,
    NINE_ROUTER_ENABLED,
    SYNC_SLASH_COMMANDS,
    TAROT_CARDS,
)
from .firebase_service import firebase_service
from .models import SPREADS
from bot_i18n import t as _i18n

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True


def _resolve_author_lang(ctx) -> str:
    """Best-effort language detection for prefix-command error replies.

    Prefers the caller's saved ``UserSettings.language`` (when a settings
    cache is available on the cog), falls back to the guild Discord locale,
    then to ``DEFAULT_LANGUAGE``. Catches *everything* so an error-path
    lookup never raises a second exception.
    """
    try:
        from .config import DEFAULT_LANGUAGE
        cog = getattr(getattr(ctx, "bot", None), "get_cog", lambda _n: None)("TarotSystem")
        if cog is not None:
            author_id = getattr(getattr(ctx, "author", None), "id", None)
            guild_id = getattr(getattr(ctx, "guild", None), "id", None)
            if author_id is not None:
                user_settings, _server_settings = cog._get_settings(author_id, guild_id)
                lang = user_settings.get_lang()
                if lang:
                    return lang
        guild = getattr(ctx, "guild", None)
        if guild is not None:
            loc = getattr(guild, "preferred_locale", None)
            if loc:
                short = loc.split("-")[0].lower()
                if short in ("id", "en", "pt", "es", "de"):
                    return short
        return DEFAULT_LANGUAGE
    except Exception:
        return "id"

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
    case_insensitive=True,
)


async def setup_hook():
    """Called once when the bot is connecting to Discord.

    Loads the TarotSystem cog, syncs slash commands if enabled.
    """
    await bot.add_cog(TarotSystem(bot))
    logger.info("TarotSystem cog loaded successfully")

    if SYNC_SLASH_COMMANDS:
        try:
            synced_commands = await bot.tree.sync()
            logger.info(f"Synced {len(synced_commands)} slash command(s)")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}", exc_info=True)


bot.setup_hook = setup_hook


@bot.event
async def on_ready():
    """Print boot banner and set presence."""
    print(f'\n{"=" * 50}')
    print(f"✅ {bot.user} is now online!")
    print("🔮 Tarot Bot v2.5.0")
    print(f"📊 {len(TAROT_CARDS)} tarot cards loaded")
    print(f"🃏 {len(SPREADS)} spread types available")
    print("🌐 Languages: Indonesian, English")
    print("🎭 Modes: simple, deep, gentle, direct")
    print(f'🤖 AI: {"9Router" if NINE_ROUTER_ENABLED else "Gemini"} ({GEMINI_MODEL})')
    print(f'✨ Slash commands: {"sync enabled" if SYNC_SLASH_COMMANDS else "sync disabled"}')
    print(f'☁️ Firebase: {"enabled" if firebase_service.is_enabled() else "disabled"}')
    print(f'{"=" * 50}\n')

    logger.info(f"Logged in as {bot.user.name} ({bot.user.id})")

    activity = discord.Activity(
        type=discord.ActivityType.listening,
        name="!help | /help | Tarot Readings",
    )
    await bot.change_presence(activity=activity)


@bot.event
async def on_command_error(ctx, error):
    """Catch-all error handler for prefix commands.

    Slash command errors are handled by the global app_command_error handler
    on the cog itself.
    """
    try:
        if isinstance(error, commands.CommandNotFound):
            await ctx.send(
                "❌ Command not found. Use `!help` to see all available commands."
            )
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"⚠️ Missing argument. Use `!help {ctx.command.name}` for proper usage."
            )
        elif isinstance(error, commands.BadArgument):
            await ctx.send(
                "⚠️ Invalid argument. Please check your input and try again."
            )
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("⚠️ You don't have permission to use this command.")
        elif isinstance(error, commands.CheckFailure):
            # BOT_ADMIN_IDS guard (or other custom @commands.check) denied.
            # Translate to the caller's preferred language so the rejection
            # is friendly, not a raw `CheckFailure: ...` dump.
            author_id = getattr(getattr(ctx, "author", None), "id", None)
            language = _resolve_author_lang(ctx)
            try:
                msg = _i18n("errors.admin_only", lang=language, user_id=author_id)
            except Exception:
                msg = (
                    f"🔒 This command is restricted to bot admins. "
                    f"Your user ID: `{author_id}`."
                )
            try:
                await ctx.send(msg)
            except discord.NotFound:
                pass
        elif isinstance(error, commands.CommandOnCooldown):
            retry_after = int(error.retry_after) + 1
            minutes, seconds = divmod(retry_after, 60)
            wait_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
            msg = (
                f"⏳ **Cooldown aktif!** Tunggu **{wait_str}** sebelum `/tarot` lagi.\n"
                "💎 *Premium users punya cooldown lebih cepat. Cek `!premium`*"
            ) if ctx.author.id and ctx.guild else (
                f"⏳ **Cooldown!** Wait **{wait_str}** before `/tarot` again."
            )
            try:
                await ctx.send(msg)
            except discord.NotFound:
                pass
        elif isinstance(error, discord.NotFound) and "Unknown interaction" in str(error):
            pass
        else:
            logger.error(f"Command error: {error}", exc_info=True)
            try:
                await ctx.send(
                    f"💥 An unexpected error occurred. Please try again later.\n"
                    f"```{error.__class__.__name__}: {str(error)[:100]}```"
                )
            except discord.NotFound:
                pass
    except Exception as e:
        logger.error(f"Error in error handler: {e}")


@bot.event
async def on_message(message):
    """Required so prefix commands are processed."""
    if message.author.bot:
        return
    await bot.process_commands(message)


def main():
    """Entry point: load token, run the bot."""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ ERROR: DISCORD_TOKEN not found!")
        print("\n📝 Create a file named '.env' in the same directory with:")
        print("DISCORD_TOKEN=your_bot_token_here")
        print("NINE_ROUTER_ENABLED=true")
        print("GEMINI_MODEL=kr/claude-sonnet-4.5")
        print("\n🔗 Get token from: https://discord.com/developers/applications")
        return

    try:
        bot.run(token)
    except discord.LoginFailure:
        print("❌ Invalid token. Please check your DISCORD_TOKEN in .env file.")
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")


def run():
    """Public alias used by main.py."""
    main()