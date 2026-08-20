# 🔮 Tarot Discord Bot

A self-hostable Discord bot for tarot readings, daily card draws, personal reflection, and AI-assisted interpretation. Built with Python and discord.py, ships with **24-language i18n**, hybrid (prefix + slash) commands, optional 9Router AI integration, optional Firebase cloud sync, and a structured logging pipeline that can mirror to Discord itself.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![discord.py](https://img.shields.io/badge/discord.py-2.7-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Languages](https://img.shields.io/badge/i18n-24%20languages-orange)
![Commands](https://img.shields.io/badge/commands-36-purple)
![AI](https://img.shields.io/badge/AI-9Router%20(OpenAI--compatible)-blueviolet)

---

## ✨ Features

### 🔮 Tarot core
- **78 Rider–Waite cards** with detailed meanings, keywords, and orientation-aware (upright/reversed) interpretations
- **11 reading spreads**: `single`, `three`, `celtic`, `love`, `career`, `yesno`, `weekly`, `decision`, `selfcare`, `shadow`, `relationship`
- **Daily & weekly readings** with per-user cooldowns (24h / 7d)
- **Visual card images** rendered with PIL for `!daily`
- **Reading history** per user with export (`!exportdata`) and wipe (`!deletedata confirm`)
- **Personal insights** based on reading patterns
- **Journal entries** attached to any reading
- **Favourite flag** for any reading (`!favourite <id>`)
- **Share reading** to a channel or DM (`!share <id> [@user]`)

### 🌍 24-language i18n
- 🇮🇩 Bahasa Indonesia (default) · 🇬🇧 English · 🇵🇹 Português · 🇪🇸 Español · 🇩🇪 Deutsch
- 🌎 Español (LATAM) · 🇫🇷 Français · 🇭🇺 Magyar · 🇮🇹 Italiano · 🇳🇱 Nederlands · 🇵🇱 Polski · 🇷🇴 Română · 🇧🇷 Português (BR) · 🇸🇪 Svenska · 🇻🇳 Tiếng Việt · 🇹🇷 Türkçe · 🇨🇿 Čeština · 🇷🇺 Русский · 🇺🇦 Українська · 🇹🇭 ไทย · 🇨🇳 简体中文 · 🇯🇵 日本語 · 🇹🇼 繁體中文 · 🇰🇷 한국어
- Switch on the fly: `!language [code]` or `/language`
- YAML-driven translation; fallback chain `target → en → id`
- 250+ keys parity-checked across all 24 files

### 🤖 AI interpretation
- **9Router (or any OpenAI-compatible endpoint)** — set `NINE_ROUTER_BASE_URL` + `NINE_ROUTER_API_KEY` + `NINE_ROUTER_MODEL`
- **Choose your model** at runtime: `!aimodel [model_id]` from the list at `!aimodels`
- **Silent fallback** — if the endpoint is unreachable, the bot keeps the local card explanations and shows no error banner
- **Tunable**: temperature, top-p, max tokens, timeout, retries, backoff
- **Concurrency cap** (`AI_CALL_SEMAPHORE = 5` in `bot/ai.py`) so a busy server doesn't drown the endpoint

### 🎨 Discord-native UI
- **Hybrid commands** — every command works as `!prefix` and `/slash`
- **Interactive dropdowns** in `!help` and `!botinfo` — pick a category, get an ephemeral detail panel
- **Rich embeds** colour-coded by spread type
- **Link buttons** in `!invite`, `!vote`, `!donate`, `!source`
- **DM mode** (`!tarotdm`) for private readings

### 🔒 Admin & safety
- **6 admin-gated commands** (`!aimodels`, `!botinfo`, `!firebase`, `!syncdb`, `!serverstats`, `!resetcooldown`) restricted to `BOT_ADMIN_IDS` or Discord Administrator role
- **Cooldown errors are handled** in both prefix and slash surfaces — no "Task exception was never retrieved" warnings in logs
- **User-owned data** — export anytime, delete anytime
- **No telemetry** sent anywhere except to the AI endpoint (only when AI is enabled)
- **`message_content` intent only** — no `members` privileged intent required

### 📜 Logging
- **Console** (`stdout`, INFO+) — always on
- **File** (`bot.log` next to `saves/`, INFO+, UTF-8) — always on
- **Optional Discord webhook** — set `DISCORD_LOG_WEBHOOK_URL` to mirror WARNING+ records to a Discord channel. Throttled (default 5s between posts), queue-bounded (100), JWT and snowflake-ID redactor built in.

---

## 📋 Requirements

- **Python 3.10+** (tested on 3.14)
- **Discord bot token** — https://discord.com/developers/applications
- **9Router (or any OpenAI-compatible endpoint)** — *only if you want AI interpretations*
- **Optional: Firebase project** for cloud sync

---

## 🚀 Installation

### 1. Clone & enter the repo
```bash
git clone https://github.com/Vey-Project/tarot-bot-discord.git
cd tarot-bot-discord
```

### 2. Create a virtual environment
```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
```bash
cp .env.example .env
```

Minimum required:
```env
# Required — your Discord bot token
DISCORD_TOKEN=your_bot_token_here

# Comma-separated Discord user IDs allowed to run bot admin commands.
# (Discord Administrator role also bypasses the check.)
BOT_ADMIN_IDS=789065787276132392

# Slash command sync at boot
SYNC_SLASH_COMMANDS=true

# id = Indonesian (default), en = English, pt = Portuguese,
# es = Spanish, de = German, + 19 more (see Supported Languages)
DEFAULT_LANGUAGE=id
```

Optional — AI interpretation:
```env
NINE_ROUTER_ENABLED=true
NINE_ROUTER_BASE_URL=http://localhost:20128/v1
NINE_ROUTER_API_KEY=your_9router_key_here
NINE_ROUTER_MODEL=kr/claude-sonnet-4.5
NINE_ROUTER_API_TIMEOUT=60
NINE_ROUTER_MAX_OUTPUT_TOKENS=4000
NINE_ROUTER_TEMPERATURE=0.75
NINE_ROUTER_TOP_P=0.9
NINE_ROUTER_MAX_RETRIES=3
NINE_ROUTER_RETRY_BACKOFF=1.0
```

Optional — Firebase cloud sync:
```env
FIREBASE_ENABLED=false
FIREBASE_CREDENTIALS_PATH=./firebase-credentials.json
FIREBASE_DATABASE_URL=https://your-project.firebaseio.com
```

Optional — Discord webhook logging:
```env
DISCORD_LOG_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_LOG_LEVEL=WARNING          # DEBUG / INFO / WARNING / ERROR
DISCORD_LOG_THROTTLE_SECONDS=5.0   # min seconds between webhook posts
```

Optional — Support / community links:
```env
DONATE_KOFI_URL=https://ko-fi.com/your_handle
DONATE_PAYPAL_URL=https://paypal.me/your_handle
DONATE_MESSAGE=
TOPGG_VOTE_URL=https://top.gg/bot/your_bot_id/vote
```

> ⚠️ **Never commit `.env`** — it's already in `.gitignore`. Use `.env.example` for documentation.

### 5. Run
```bash
python main.py
```

On a clean start you should see:
```
2026-08-20 21:39:58 [INFO] bot.cog: Loaded 120 users' readings
2026-08-20 21:39:58 [INFO] bot.bot: Synced 36 slash command(s)
2026-08-20 21:39:59 [INFO] bot.bot: Logged in as YOUR_BOT_NAME (...)
```

---

## 🗂️ Project Structure

```
tarot-bot-discord/
├── main.py                       # Entry point (load_dotenv + bot.run)
├── bot/                          # Main package
│   ├── __init__.py               #   Package wiring, exports run() & bot
│   ├── bot.py                    #   Bot instance, setup_hook, event handlers, error path
│   ├── cog.py                    #   TarotSystem cog — all 36 commands + admin check
│   ├── ai.py                     #   NineRouterInterpreter (OpenAI-compatible + retry)
│   ├── image_gen.py              #   CardImageGenerator (PIL rendering)
│   ├── log_handler.py            #   Discord webhook log handler (throttled + redactor)
│   ├── models.py                 #   Enums, dataclasses, UserSettings, ServerSettings
│   ├── views.py                  #   Discord UI dropdowns (botinfo, help)
│   ├── firebase_service.py       #   Firebase singleton + async wrappers
│   ├── changelog.py              #   In-bot changelog data
│   ├── utils.py                  #   safe_task helper
│   └── config.py                 #   Env loading + path constants
├── bot_i18n.py                   # i18n loader (t(), get() helpers, fallback chain)
├── tests/
│   └── test_orientation_symbol.py  # runnable self-check (no framework)
├── requirements.txt              # Python dependencies
├── .env.example                  # Safe template for environment vars
├── .env                          # Your real secrets (gitignored)
├── locales/                      # YAML translations (24 files)
│   ├── id.yml  en.yml  pt.yml  es.yml  de.yml     # original 5 (native translated)
│   ├── es-419.yml  fr.yml  hu.yml  it.yml  nl.yml
│   ├── pl.yml  ro.yml  pt-BR.yml  sv.yml  vi.yml
│   ├── tr.yml  cs.yml  ru.yml  uk.yml  th.yml
│   └── zh-CN.yml  ja.yml  zh-TW.yml  ko.yml
├── data/
│   └── tarot_cards.json          # 78-card Rider-Waite database
├── saves/                        # local data (gitignored)
│   ├── readings.json             #   reading history
│   ├── journals/                 #   per-user journal entries
│   ├── settings/                 #   per-user & per-server settings
│   └── bot.log                   #   structured log file (created on first run)
└── images/                       # Card artwork (78 jpg files, 768x1376)
```

---

## 🌍 Supported Languages

| Code | Language | Code | Language |
|------|----------|------|----------|
| `id` | Bahasa Indonesia (default) | `ro` | Română |
| `en` | English | `pt-BR` | Português (Brasil) |
| `pt` | Português | `sv` | Svenska |
| `es` | Español | `vi` | Tiếng Việt |
| `de` | Deutsch | `tr` | Türkçe |
| `es-419` | Español (Latinoamérica) | `cs` | Čeština |
| `fr` | Français | `ru` | Русский |
| `hu` | Magyar | `uk` | Українська |
| `it` | Italiano | `th` | ไทย |
| `nl` | Nederlands | `zh-CN` | 简体中文 |
| `pl` | Polski | `ja` | 日本語 |
|  |  | `zh-TW` | 繁體中文 |
|  |  | `ko` | 한국어 |

Switch with `!language [code]` or `/language [code]`. The `cooldown.global` and 250+ other strings are fully translated; 19 of the 24 files are English-derived pending native-speaker review.

---

## 🎮 Commands

The bot registers **36 hybrid commands** — every command below works as both `!prefix` and `/slash`.

### 🔮 Public commands (30)

| Command | Description |
|---------|-------------|
| `!tarot [spread] [question]` | Get a tarot reading |
| `!tarotdm [spread] [question]` | Send a reading via DM (privacy mode) |
| `!card [name]` | Detailed card info |
| `!cards [category]` | Browse cards by category |
| `!daily` | Your daily card (24h cooldown) |
| `!weekly` | Your weekly spread (7-day cooldown) |
| `!history [count]` | View past readings |
| `!insight` | Personalised insights from your reading patterns |
| `!journal add <id> <note>` | Attach a journal note to a reading |
| `!journal` | View your journal entries |
| `!favourite [id]` | Toggle favourite (or list favourites) |
| `!share <id> [@user]` | Share a reading to a channel or DM |
| `!exportdata` | Export your data as JSON |
| `!deletedata confirm` | Wipe your data |
| `!feedback <message>` | Send feedback to the bot owner |
| `!invite` | OAuth2 invite link + vote button |
| `!vote` | top.gg vote link |
| `!donate` | Ko-fi / PayPal support links |
| `!source` | Repo, version, license info |
| `!changelog` | Recent bot changes |
| `!help` | Interactive help (dropdown) |
| `!language [code]` | Switch language |
| `!mode [mode]` | Switch reading style (`simple` / `deep` / `gentle` / `direct`) |
| `!aimodel [model_id]` | Pick the AI model for interpretation |
| `!aion` / `!aioff` | Toggle AI on/off per user |
| `!aistatus` | Show AI status |
| `!remind <target>` | Set daily/weekly/tarotdm reminder |
| `!profile [@user]` | Show reading stats for a user |
| `!reset_settings` | Reset your settings to defaults |
| `!ping` | Latency check |
| `!uptime` | Bot uptime + boot time |

### 🔒 Admin commands (6 — `BOT_ADMIN_IDS` or Administrator role)

| Command | Description |
|---------|-------------|
| `!aimodels` | List available AI models (fetched live, with fallback) |
| `!botinfo` | Bot stats + interactive feature picker |
| `!firebase` | Firebase sync status |
| `!syncdb` | Force-push reading history to Firebase |
| `!serverstats` | Server-wide stats |
| `!resetcooldown [user]` | Reset a user's daily/weekly cooldown |

Non-admins get a friendly localised message (not a traceback).

### 📊 Spread types

| Spread | Cards | Use case |
|--------|------:|----------|
| `single` | 1 | Quick guidance |
| `three` | 3 | Past / Present / Future |
| `yesno` | 3 | Yes / No guidance |
| `love` | 6 | Relationship insights |
| `career` | 6 | Work & success |
| `weekly` | 5 | Weekly overview |
| `decision` | 5 | Decision help |
| `selfcare` | 5 | Self-care reflection |
| `shadow` | 5 | Inner shadow work |
| `relationship` | 5 | Relationship dynamics |
| `celtic` | 10 | Comprehensive Celtic Cross |

### 🎴 Card categories
`major` (22) · `wands` (14) · `cups` (14) · `swords` (14) · `pentacles` (14) · `all` (78)

---

## 🤖 AI Interpretation

The bot supports **any OpenAI-compatible endpoint** via 9Router. There is **no fallback provider** — if the endpoint is unreachable, the bot **silently** omits the AI interpretation and shows your local card explanations instead. No error banner appears.

### Switching providers

Point `NINE_ROUTER_BASE_URL` and `NINE_ROUTER_API_KEY` at any OpenAI-compatible server:

| Provider | `NINE_ROUTER_BASE_URL` |
|----------|------------------------|
| 9Router (local) | `http://localhost:20128/v1` |
| OpenAI | `https://api.openai.com/v1` |
| Ollama (local) | `http://localhost:11434/v1` |
| LM Studio | `http://localhost:1234/v1` |

Users pick the model with `!aimodel [model_id]` and list available models with `!aimodels`.

### Resilience settings

| Env var | Default | What it does |
|---------|--------:|--------------|
| `NINE_ROUTER_API_TIMEOUT` | 60 | Per-request timeout (seconds) |
| `NINE_ROUTER_MAX_OUTPUT_TOKENS` | 4000 | Max output tokens per response |
| `NINE_ROUTER_TEMPERATURE` | 0.75 | Sampling temperature |
| `NINE_ROUTER_TOP_P` | 0.9 | Nucleus sampling |
| `NINE_ROUTER_MAX_RETRIES` | 3 | Silent retries before fallback |
| `NINE_ROUTER_RETRY_BACKOFF` | 1.0 | Linear backoff between retries (seconds) |

### Concurrency limit
Up to **5 AI calls run in parallel** (`AI_CALL_SEMAPHORE = 5` in `bot/ai.py`). Tweak the constant if your endpoint can handle more.

---

## 🔥 Firebase (optional)

Cloud sync is **off by default**. To enable:

1. Create a Firebase project → Firestore database
2. Download service-account credentials JSON
3. Save as `firebase-credentials.json` (gitignored)
4. Set in `.env`:
   ```env
   FIREBASE_ENABLED=true
   FIREBASE_CREDENTIALS_PATH=./firebase-credentials.json
   ```
5. Restart the bot — you should see `Loaded X users from Firebase` in logs.

Without Firebase, all data stays in local JSON files under `saves/`.

---

## 📜 Logging

The bot logs to **three sinks** simultaneously:

| Sink | Always on? | Format | Default level | Where to set |
|------|:---:|--------|:---:|--------------|
| **Console** (`stdout`) | yes | `[TIME] [LEVEL] logger: msg` | INFO+ | `bot/bot.py:_setup_logging` |
| **File** (`saves/../bot.log`) | yes | same as console | INFO+ | `_setup_logging` |
| **Discord webhook** | no | ```` ```\nLEVEL logger\nmsg\n``` ```` | WARNING+ (configurable) | `DISCORD_LOG_WEBHOOK_URL`, `DISCORD_LOG_LEVEL` |

### Webhook specifics
- **Throttled**: minimum 5s between posts (`DISCORD_LOG_THROTTLE_SECONDS`)
- **Queue-bounded**: 100 records; overflow is dropped and counted (warning logged)
- **Redaction**: JWT-shaped tokens (`a.b.c` with 20+ char segments) and Discord snowflake IDs (17–20 digits) are masked to `1234…5678` before posting
- **Lifecycle**: the pump task starts before `bot.start(token)` and stops on shutdown, so nothing leaks

```env
DISCORD_LOG_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_LOG_LEVEL=WARNING
DISCORD_LOG_THROTTLE_SECONDS=5.0
```

---

## 🔒 Privacy & Security

- ✅ **User-owned data** — `!exportdata` (download JSON) and `!deletedata confirm` (wipe) anytime
- ✅ **No telemetry** sent anywhere except to the AI endpoint (only when AI is enabled)
- ✅ **Discord tokens and API keys** live only in `.env` (gitignored)
- ✅ **`members` privileged intent is disabled** — bot only requires `message_content`
- ✅ **Local-first** storage; cloud sync is opt-in
- ✅ **Admin-gated commands** for sensitive operations (sync, cooldowns, internal stats)
- ✅ **Webhook log redactor** masks tokens and snowflake IDs before they ever reach Discord

---

## ⚠️ Discord Privileged Intents

At **10,000+ users**, Discord requires verification for the `message_content` privileged intent. Steps to apply:

1. Open https://discord.com/developers/applications/{APP_ID}/bot
2. Click **"Request Verification"**
3. Fill in:
   - Bot purpose (tarot readings for entertainment/self-reflection)
   - Why `message_content` is needed (hybrid prefix + slash commands)
   - Data handling (local storage, user can export/delete)
   - Privacy policy URL (use a generator like privacypolicies.com if you don't have one)
4. Submit — review typically takes 2–4 weeks

**While waiting for verification**, your options:
- Keep using slash commands (`/tarot`) — works without verification
- The prefix is hardcoded to `!` in `bot/bot.py`; if you need to disable prefix commands entirely, edit `command_prefix="!"` before deploying

---

## 🛠️ Development

### Running syntax / smoke tests
```bash
# Cheap AST check across all source files
python -c "import ast; [ast.parse(open(f).read()) for f in ['main.py','bot/bot.py','bot/cog.py','bot/ai.py','bot/log_handler.py','bot_i18n.py']]; print('AST OK')"

# Runnable self-check (orientation symbol + AST)
python tests/test_orientation_symbol.py

# Verify card database (78 cards, 78 images)
python check_cards.py

# Full import smoke test (loads bot + cog)
python -c "from bot import bot, run; print('Bot loads OK')"
```

### Adding a new command
```python
# In bot/cog.py, add a new method to the TarotSystem class:
@commands.hybrid_command(name='mycmd', description='…')
async def my_command(self, ctx, arg: str = None):
    user_settings, _server_settings = self._get_settings(
        ctx.author.id, ctx.guild.id if ctx.guild else None
    )
    language = user_settings.get_lang()
    msg = _("mycmd.greeting", lang=language, name=arg)
    await ctx.send(msg)
```

Then add `mycmd.greeting` to **all 24** locale files. The bot will warn if you forget one.

### Project conventions
- **i18n first** — every user-visible string lives in `locales/*.yml`, no hardcoded messages in `bot/cog.py`
- **Hybrid commands only** — every command should be `@commands.hybrid_command(...)`
- **Avoid shadowing `_`** — it's the `t()` alias. Use `_server_settings` for unused tuple unpacks
- **Silent failure** — AI is a "nice-to-have" layer. If anything goes wrong, swallow gracefully and keep the local card explanations visible
- **No unrequested abstractions** — one implementation, one call site, no factories

---

## 📊 Capacity & Scaling

| Scenario | Comfortable | Needs migration |
|----------|-------------|-----------------|
| **Servers** | 1–20 | 50+ → SQLite/Firestore |
| **Registered users** | < 5k | 10k+ → SQLite/Firestore |
| **Concurrent AI users** | 5 (semaphore) | raise `AI_CALL_SEMAPHORE` in `bot/ai.py` |
| **`readings.json` size** | < 10 MB | > 50 MB → migrate |
| **`bot.log` size** | < 50 MB | rotate or use `RotatingFileHandler` |

If you start hitting limits, the **first refactor** should be moving `readings.json` → SQLite. JSON-with-dict-rebuild scales poorly once files exceed a few MB.

---

## 🐛 Troubleshooting

**Bot won't start:**
- Check `.env` exists and `DISCORD_TOKEN` is filled
- Python 3.10+ required (3.14 tested ✅)
- Run `pip install -r requirements.txt` again

**Commands not responding:**
- Confirm `message_content` intent is enabled in Discord Developer Portal
- Confirm bot has permission to read & send messages in the channel
- For DMs: ensure user has DMs open

**Cooldown messages not in your language:**
- Run `!language <your_code>` to set it (the default may be `id` for Indonesian)
- Check the language list above — not all Discord UI languages are supported

**AI interpretation missing:**
- `!aistatus` to check configuration
- Verify `NINE_ROUTER_BASE_URL` is reachable (`curl http://localhost:20128/v1/models`)
- Check `bot.log` for HTTP errors
- If 9Router is down, this is **expected** — the bot stays silent rather than showing an error

**Discord webhook log not posting:**
- `DISCORD_LOG_WEBHOOK_URL` must be set
- `DISCORD_LOG_LEVEL` defaults to `WARNING`; INFO messages will not post
- Check `bot.log` for `Discord webhook log handler` startup line
- The handler throttles — a flood of warnings only generates one post per 5s

**"Command ini hanya untuk admin bot" message:**
- Add your Discord user ID to `BOT_ADMIN_IDS` in `.env`, or
- Get a server role with Discord Administrator permission

**`readings.json` getting huge:**
- Expected at high traffic — see Capacity section above

---

## 🧱 Architecture notes

- **No background threads for IO**: every external call (AI, Firebase, webhook) is async and bounded by an `asyncio.Semaphore`
- **Webhook log handler is transport-level**: call sites use `logger.warning(...)` — throttling and redaction happen in the handler, not the caller
- **Settings/history are JSON files rebuilt at startup**: simple, debuggable, easy to migrate later
- **i18n loader caches parsed YAML in-process**: clearing the cache requires a restart
- **Cooldown errors are caught in both surfaces** (`cog_command_error` for slash, `on_command_error` for prefix) — you won't see "Task exception was never retrieved" warnings

---

## 📝 License

MIT — see [LICENSE](LICENSE).

---

## 🙏 Acknowledgments

- Traditional Rider–Waite tarot symbolism
- [discord.py](https://github.com/Rapptz/discord.py) library
- [9Router](https://github.com/decolua/9router) for the OpenAI-compatible proxy
- All users providing feedback
