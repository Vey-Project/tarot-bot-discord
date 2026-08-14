# 🔮 Tarot Discord Bot

A feature-rich Discord bot for tarot readings, daily card draws, and personal reflection. Built with Python and Discord.py, with full **multi-language support** (Indonesian, English, Portuguese, Spanish, German) and an **interactive dropdown UI**.

![Tarot Bot Banner](https://img.shields.io/badge/Tarot-Wisdom-purple)
![Python Version](https://img.shields.io/badge/python-3.10+-blue)
![Discord.py](https://img.shields.io/badge/discord.py-2.7-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Languages](https://img.shields.io/badge/i18n-5%20languages-orange)

## ✨ Features

### 🔮 **Core Features**
- **78 Authentic Tarot Cards** with detailed meanings, keywords, and orientation-aware interpretations
- **11 Reading Spreads**: single, three, celtic, love, career, yesno, weekly, decision, selfcare, shadow, relationship
- **Daily & Weekly Readings** with personal cooldowns
- **AI Interpretations** (optional) via 9Router — pick your own model
- **Reading History** stored per user with export/delete controls
- **Personal Insights** based on reading patterns
- **Visual Spread Layouts** generated per reading

### 🌐 **Multi-Language Support**
- 🇮🇩 Bahasa Indonesia (default)
- 🇬🇧 English
- 🇵🇹 Português
- 🇪🇸 Español
- 🇩🇪 Deutsch
- Switch on the fly with `!language [code]`
- YAML-based i18n with fallback chain (`target → en → id`)

### 🎨 **Interactive Discord UI**
- **Dropdown menus** in `!help` and `!botinfo` — pick a category/feature to see details
- **Hybrid commands** — support both `!prefix` and `/slash` from the same code
- **Color-coded embeds** by spread type
- **Ephemeral replies** for detail panels (only the user sees them)
- **Pagination** for card lists

### 🔧 **Technical Highlights**
- Async-first architecture (discord.py 2.7 + aiohttp)
- YAML-driven localization (zero hardcoded strings)
- Optional **Firebase Firestore** sync for cross-device data
- Pluggable AI backend — currently 9Router, swap by changing the URL
- Privacy-first: users can `!exportdata` or `!deletedata` at any time

## 📋 Requirements

- **Python 3.10+** (tested on 3.14)
- Discord Bot Token
- 9Router (or OpenAI-compatible endpoint) — *only if you want AI interpretations*
- Optional: Firebase project for cloud sync

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
Copy the template and fill in your secrets:
```bash
cp .env.example .env
```

Edit `.env` with at minimum:
```env
# Required — your Discord bot token
DISCORD_TOKEN=your_bot_token_here

# AI interpretation (via 9Router, OpenAI-compatible)
NINE_ROUTER_ENABLED=true
NINE_ROUTER_BASE_URL=http://localhost:20128/v1
NINE_ROUTER_API_KEY=
GEMINI_MODEL=kr/claude-sonnet-4.5

# Optional — direct Gemini fallback when 9Router is unavailable
# (leave blank to disable fallback)
GEMINI_API_KEY=

# Slash command sync at boot
SYNC_SLASH_COMMANDS=true

# id = Indonesian, en = English, pt = Portuguese, es = Spanish, de = German
DEFAULT_LANGUAGE=id

# Optional — Firebase cloud sync (see .env.example for full options)
FIREBASE_ENABLED=false
FIREBASE_CREDENTIALS_PATH=./firebase-credentials.json
```

The prefix `!` is hardcoded (see `bot/bot.py`); the bot is hybrid (prefix + slash).
All env vars are documented in `.env.example` — start there.

> ⚠️ **Never commit `.env`** — it's already in `.gitignore`. Use `.env.example` for documentation.

### 5. Run
```bash
python main.py
```

If everything is wired correctly you should see:
```
[TIMESTAMP] - __main__ - INFO - Loaded 78 tarot cards
[TIMESTAMP] - __main__ - INFO - Logged in as TAROT BETA (...)
```

## 🗂️ Project Structure

```
tarot-bot-discord/
├── main.py                    # Thin entry point (load_dotenv + bot.run)
├── bot/                       # Main package
│   ├── __init__.py            #   Package wiring, exports run() & bot
│   ├── bot.py                 #   Bot instance, setup_hook, event handlers
│   ├── cog.py                 #   TarotSystem cog — all 30 commands
│   ├── ai.py                  #   GeminiTarotInterpreter (9Router + Gemini)
│   ├── image_gen.py           #   CardImageGenerator (PIL rendering)
│   ├── models.py              #   Enums, dataclasses, UserSettings
│   ├── views.py               #   Discord UI dropdowns (botinfo, help)
│   ├── firebase_service.py    #   Firebase singleton + async wrappers
│   ├── logging_webhook.py     #   Discord webhook log handler
│   ├── utils.py               #   safe_task helper
│   └── config.py              #   Env loading + path constants
├── bot_i18n.py                # i18n loader (t(), get() helpers)
├── requirements.txt           # Python dependencies
├── .env.example               # Safe template for environment vars
├── .env                       # Your real secrets (gitignored)
├── locales/                   # YAML translations
│   ├── id.yml                 #   🇮🇩 Indonesian (default)
│   ├── en.yml                 #   🇬🇧 English
│   ├── pt.yml                 #   🇵🇹 Portuguese
│   ├── es.yml                 #   🇪🇸 Spanish
│   └── de.yml                 #   🇩🇪 German
├── data/
│   └── tarot_cards.json       # 78-card Rider-Waite database
├── saves/
│   ├── readings.json          # Local reading history
│   ├── journals/              # Per-user journal entries
│   └── settings/              # Per-user & per-server settings
└── images/                    # Optional card artwork
```

## 🌍 Adding a New Language

The bot uses a simple YAML-driven i18n system. To add a 6th language (e.g., French):

1. **Add the locale code to `bot_i18n.py`:**
   ```python
   SUPPORTED_LOCALES = ["id", "en", "pt", "es", "de", "fr"]
   DEFAULT_LOCALE = "id"
   ```

2. **Copy `en.yml` → `locales/fr.yml`** and translate every value.

3. **Update `language.*` keys** in *all* locale files to mention the new language.

4. **Add `get_locale_name("fr")` → `"Français"`** in `bot_i18n.py`.

5. **Verify parity:**
   ```bash
   python -c "import yaml; from pathlib import Path
   keys = {l: set(yaml.safe_load(Path(f'locales/{l}.yml').read_text()).keys())
           for l in ['id','en','pt','es','de','fr']}
   print('Keys per locale:', {k: len(v) for k,v in keys.items()})
   base = keys['id']
   for l, v in keys.items():
       print(f'{l}: {\"✅ matches\" if v == base else f\"❌ diff: {base ^ v}\"}')"
   ```

## 🎮 Commands

The bot registers **hybrid commands** — every command below works with **both** `!prefix` and `/slash`.

### 🔮 **Main Commands**
| Command | Description |
|---------|-------------|
| `!tarot [spread] [question]` | Get a tarot reading |
| `!tarotdm [spread] [question]` | Send reading via DM (privacy mode) |
| `!card [name]` | Detailed card info |
| `!cards [category]` | Browse cards by category |
| `!daily` | Your daily card (24h cooldown) |
| `!weekly` | Your weekly spread (7-day cooldown) |
| `!history [count]` | View past readings |
| `!insight` | Personalized insights |
| `!journal [add/list]` | Personal reflection notes |
| `!exportdata` | Export your data (JSON) |
| `!deletedata confirm` | Delete your data |
| `!help` | Interactive help menu (dropdown) |
| `!botinfo` | Bot stats + interactive feature picker (dropdown) |
| `!language [code]` | Switch language (`id`, `en`, `pt`, `es`, `de`) |
| `!mode [mode]` | Switch reading style (`simple`, `deep`, `gentle`, `direct`) |
| `!aimodels` | List available AI models |
| `!aimodel [model_id]` | Pick AI model for interpretation |
| `!aion` / `!aioff` | Toggle AI on/off |
| `!aistatus` | Show AI status |
| `!firebase` | Show Firebase sync status |

### 📊 **Spread Types**

| Spread | Cards | Use case |
|--------|------:|----------|
| `single` | 1 | Quick guidance |
| `three` | 3 | Past / Present / Future |
| `love` | 6 | Relationship insights |
| `career` | 6 | Work & success |
| `yesno` | 3 | Yes / No guidance |
| `weekly` | 5 | Weekly overview |
| `decision` | 5 | Decision help |
| `selfcare` | 5 | Self-care reflection |
| `shadow` | 5 | Inner shadow work |
| `relationship` | 5 | Relationship dynamics |
| `celtic` | 10 | Comprehensive Celtic Cross |

### 🎴 **Card Categories**
`major` (22) · `wands` (14) · `cups` (14) · `swords` (14) · `pentacles` (14) · `all` (78)

## 🤖 AI Interpretation (Optional)

The bot supports **any OpenAI-compatible endpoint**. By default it's wired to **9Router** (an OpenAI-compatible proxy for multiple providers).

### Switching providers

Point `NINE_ROUTER_BASE_URL` and `NINE_ROUTER_API_KEY` at any OpenAI-compatible server:

| Provider | `NINE_ROUTER_BASE_URL` |
|----------|------------------------|
| 9Router (local) | `http://localhost:20128/v1` |
| OpenAI | `https://api.openai.com/v1` |
| Ollama (local) | `http://localhost:11434/v1` |
| LM Studio | `http://localhost:1234/v1` |

Users pick the model with `!aimodel [model_id]` and list available models with `!aimodels`.

To fall back to direct Gemini API when 9Router is down, set both `NINE_ROUTER_API_KEY` (primary) and `GEMINI_API_KEY` (fallback).

### Concurrency limit
Up to **5 AI calls run in parallel** (`AI_CALL_SEMAPHORE = 5`). Tweak `AI_CALL_SEMAPHORE` in `bot/ai.py` if your endpoint can handle more.

## 🔥 Firebase (Optional)

Cloud sync is **off by default**. To enable:

1. Create a Firebase project → Firestore database.
2. Download service-account credentials JSON.
3. Save as `firebase-credentials.json` (gitignored).
4. Set in `.env`:
   ```env
   FIREBASE_ENABLED=true
   FIREBASE_CREDENTIALS_PATH=./firebase-credentials.json
   ```
5. Restart the bot — you should see `Loaded X users from Firebase` in logs.

Without Firebase, all data stays in local JSON files under `saves/`.

## 🔒 Privacy & Security

- ✅ **User-owned data**: `!exportdata` (download JSON) and `!deletedata confirm` (wipe) anytime
- ✅ **No telemetry** sent anywhere except to the AI endpoint (only when AI is enabled)
- ✅ **Discord tokens** and **API keys** live only in `.env` (gitignored)
- ✅ **`members` privileged intent is disabled** — bot only requires `message_content`
- ✅ **Local-first** storage; cloud sync is opt-in

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
- Note: the prefix is currently hardcoded to `!` in `bot/bot.py`. If you need to disable prefix commands entirely, edit `command_prefix="!"` (e.g. set to an empty sentinel) before deploying

## 🛠️ Development

### Running syntax / smoke tests
```bash
# Parse all source files (cheap, no imports)
python -c "import ast; [ast.parse(open(f).read()) for f in ['main.py', 'bot/__init__.py', 'bot/bot.py', 'bot/cog.py', 'bot/ai.py', 'bot/image_gen.py', 'bot/models.py', 'bot/views.py', 'bot/config.py', 'bot/utils.py', 'bot/firebase_service.py', 'bot/logging_webhook.py']]; print('All files parse OK')"

# Full import smoke test (loads bot + cog)
python -c "from bot import bot, run; print('Bot loads OK')"
```

### Adding a new command
```python
# In bot/cog.py, add a new method to the TarotSystem class:
@commands.hybrid_command(name='mycmd', description='…')
async def my_command(self, ctx, arg: str = None):
    user_settings, _server_settings = self._get_settings(ctx.author.id, ctx.guild.id if ctx.guild else None)
    language = user_settings.get_lang()
    msg = _("mycmd.greeting", lang=language, name=arg)
    await ctx.send(msg)
```

Then add `mycmd.greeting` to all 5 locale files.

### Project conventions
- **i18n first** — every user-visible string lives in `locales/*.yml`, no hardcoded messages in `bot/cog.py`
- **Hybrid commands only** — every command should be `@commands.hybrid_command(...)`
- **Avoid shadowing `_`** — it's the `t()` alias. Use `_server_settings` for unused tuple unpacks
- **Defensive `.format()`** — only call `.format()` after checking for `None` placeholders

## 📊 Capacity & Scaling

| Scenario | Comfortable | Needs migration |
|----------|-------------|-----------------|
| **Servers** | 1–20 | 50+ → SQLite/Firestore |
| **Registered users** | < 5k | 10k+ → SQLite/Firestore |
| **Concurrent AI users** | 5 (semaphore) | raise `AI_CALL_SEMAPHORE` in `bot/ai.py` |
| **`readings.json` size** | < 10 MB | > 50 MB → migrate |

If you start hitting limits, the **first refactor** should be moving `readings.json` → SQLite. JSON-with-dict-rebuild scales poorly once files exceed a few MB.

## 🐛 Troubleshooting

**Bot won't start:**
- Check `.env` exists and `DISCORD_TOKEN` is filled
- Python 3.10+ required (3.14 tested ✅)
- Run `pip install -r requirements.txt` again

**Commands not responding:**
- Confirm `message_content` intent is enabled in Discord Developer Portal
- Confirm bot has permission to read & send messages in the channel
- For DMs: ensure user has DMs open

**AI interpretation missing:**
- `!aistatus` to check configuration
- Verify `NINE_ROUTER_BASE_URL` is reachable (`curl http://localhost:20128/v1/models`)
- Check `tarot_bot.log` for HTTP errors

**`readings.json` getting huge:**
- Expected at high traffic — see Capacity section above

## 📝 License

MIT — see [LICENSE](LICENSE).

## 🙏 Acknowledgments

- Traditional tarot symbolism
- [discord.py](https://github.com/Rapptz/discord.py) library
- [9Router](https://github.com/decolua/9router) for the OpenAI-compatible proxy
- All users providing feedback

---

⭐ **Star this repo if you find it useful!** ⭐