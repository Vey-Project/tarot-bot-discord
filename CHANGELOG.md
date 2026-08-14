# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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