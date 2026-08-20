# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-08-20

### Added
- **24-language i18n** (up from 5): added Spanish (LATAM), French, Hungarian, Italian, Dutch, Polish, Romanian, Portuguese (Brazil), Swedish, Vietnamese, Turkish, Czech, Russian, Ukrainian, Thai, Simplified Chinese, Japanese, Traditional Chinese, Korean. Native translations for `cooldown.global`, `invite.*`, `vote.*`, and `aimodels.more_models`; the rest falls back to English via the existing `target → en → id` chain.
- **Three-sink logging pipeline** (always-on console + file, optional Discord webhook mirror). Webhook handler in `bot/log_handler.py` is throttled (5s default), queue-bounded (100), and redacts JWT tokens and Discord snowflake IDs before posting. Configure via `DISCORD_LOG_WEBHOOK_URL`, `DISCORD_LOG_LEVEL`, `DISCORD_LOG_THROTTLE_SECONDS`.
- **`/invite` command**: OAuth2 invite embed with permission-bit field, benefits field, and a 🗳️ Vote button alongside the existing invite link button.
- **`/vote` command**: top.gg vote link embed (pink accent, link button). Powered by `TOPGG_VOTE_URL` / `TOPGG_BOT_ID` / `TOPGG_TOKEN` env vars.
- **`TarotCard.orientation_symbol` property** (in `bot/models.py`) — shared by `!daily` and `!card`; replaces two ad-hoc ternaries with one helper.
- **24-locale x 7-invite-key parity check** as a runnable self-check.
- **`!language` extension** — now lists all 24 supported codes; runtime help strings updated in every locale.

### Changed
- **Cooldown error handling** — `CommandOnCooldown` is now caught in both the slash (`cog_command_error`) and prefix (`on_command_error`) surfaces. Users get an ephemeral localised reply with sub-second precision (e.g. `0.4s`, `1m 5s`, `1h 1m`) instead of a "Task exception was never retrieved" warning in the logs. New `TarotSystem._format_cooldown` helper produces the same string in both code paths.
- **Bot info boot banner** is now driven by `len(get_supported_locales())` instead of a hardcoded `5`.
- **`aimodels.more_models` pluralisation** — replaced a hardcoded ternary in `cog.py` with a real i18n key (with a `{count}` parameter) and added the key to all 24 locales.
- **`botinfo` and `aimodels` admin gate** kept as-is (intentional design — confirmed).

### Removed
- **Dead file `bot/logging_webhook.py`** (124 lines, never imported). Replaced by `bot/log_handler.py`.

### Fixed
- **Cooldown errors no longer surface as `Task exception was never retrieved`** in bot logs (caught and replied to in both prefix and slash command paths).
- **YAML scalar bug** in 19 newly-added locale files: `aimodels.more_models` and `vote.rewards` were stored as literal `\n` (two characters: backslash + n) because of single-quoted YAML strings. Re-authored as double-quoted YAML so the embedded newline is real. All 24 locales now render multi-line values correctly.
- **Top-level language list in `/language` response** no longer reads "id, en, pt, es, de" — the embed now reflects the full 24-locale set via `get_supported_locales()`.
- **`bot.log` (file sink)** properly UTF-8 encoded; replaces the legacy `tarot_bot.log` path that the README used to mention.

## [1.1.0] - 2026-08-14

### Added
- Package split: monolithic `main.py` (4791 lines) split into a clean `bot/` package
  with 11 focused modules (`bot`, `config`, `utils`, `logging_webhook`,
  `firebase_service`, `models`, `image_gen`, `ai`, `views`, `cog`, `__init__`).
- Background task safety: shared `_safe_task` helper that logs failures instead
  of swallowing them silently.
- Settings cache with `on_change` callbacks for hot-reload of user preferences.
- Rotating log handler for log file rotation.
- `firebase-admin` declared in `requirements.txt` for parity with `firebase` SDK.
- 8 new community commands: `/ping`, `/uptime`, `/profile`, `/serverstats`,
  `/feedback`, `/reset_settings`, `/invite`, `/favourite`.
- 6 new commands in this release: `/remind`, `/share`, `/donate`, `/source`,
  `/changelog`, `/resetcooldown`.

### Changed
- README rewritten so environment-variable references match `.env.example`
  (no more dead links to `PREFIX=`, `API_BASE_URL`, `DEFAULT_AI_MODEL`).
- Project structure section now documents the `bot/` package layout.
- Help documentation points to `bot/cog.py` instead of the old `main.py`.

## [1.0.0] - 2026-05-08

### Added
- Initial public release.
- 78 tarot cards (Rider-Waite-Smith deck) with upright/reversed orientations.
- 11 spread types (Single, Three Card, Love, Career, Celtic Cross, …).
- Hybrid commands (prefix `!` + slash `/`).
- AI interpretation via Gemini (with 9Router gateway fallback).
- Localized UI in 5 languages: Indonesian, English, Portuguese, Spanish, German.
- Firebase Firestore + Cloud Storage sync (opt-in).
- Per-user reading history with favourites.
- Daily card and weekly reading with cooldowns.
- Journal system with per-day entries.
- A/B test framework for spread variants.
- Insight command: personal pattern analysis across history.