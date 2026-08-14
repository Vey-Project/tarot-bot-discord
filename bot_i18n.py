"""
i18n module for Tarot Bot.
Custom YAML-based loader (more reliable than python-i18n for our needs).

Phase 1 Foundation:
- YAML files in locales/ directory
- Default locale: Indonesian (id)
- Fallback chain: target → en → id (returns key if none found)
- Thread-safe with module-level cache

Usage:
    from bot_i18n import t, set_default_locale, get_default_locale
    
    msg = t('tarot.spread_unknown', lang='id')
    msg = t('cooldown.message', lang='en', wait='60s')
"""

import yaml
import threading
from pathlib import Path
from typing import Dict, Optional

# Thread-safe loader lock
_load_lock = threading.Lock()

# Locales directory
LOCALES_DIR = Path(__file__).parent / "locales"

# Cache of loaded translations
_translations_cache: Dict[str, dict] = {}

# Supported locales (Phase 4: ID, EN, PT, ES, DE)
SUPPORTED_LOCALES = ["id", "en", "pt", "es", "de"]

# Default locale for new users
DEFAULT_LOCALE = "id"

# Fallback chain if translation missing
FALLBACK_CHAIN = ["en", "id"]


def _load_locale(locale: str) -> dict:
    """Load and cache YAML translations for a locale. Returns empty dict on error."""
    if locale in _translations_cache:
        return _translations_cache[locale]
    
    with _load_lock:
        # Double-check after acquiring lock
        if locale in _translations_cache:
            return _translations_cache[locale]
        
        yaml_path = LOCALES_DIR / f"{locale}.yml"
        if not yaml_path.exists():
            _translations_cache[locale] = {}
            return {}
        
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            _translations_cache[locale] = data
            return data
        except Exception as e:
            print(f"⚠️ Failed to load locale '{locale}': {e}")
            _translations_cache[locale] = {}
            return {}


def _get_nested(data: dict, key_path: str):
    """Walk a nested dict using dot-separated path. Returns None if missing."""
    current = data
    for part in key_path.split("."):
        if not isinstance(current, dict):
            return None
        if part not in current:
            return None
        current = current[part]
    return current


def t(key: str, lang: str = None, **kwargs) -> str:
    """
    Translate a key to the target language.
    
    Args:
        key: Dot-separated path like 'tarot.spread_unknown'
        lang: Target language code ('id', 'en'). Defaults to DEFAULT_LOCALE.
        **kwargs: Placeholder values for {name} in translation string.
    
    Returns:
        Translated string. Falls back through chain (lang → en → id → key).
    
    Examples:
        >>> t('tarot.spread_unknown', lang='id')
        '❌ Spread tidak dikenal. ...'
        
        >>> t('cooldown.message', lang='en', wait='60s')
        '⏳ **Cooldown!** Wait **60s** before `/tarot` again.'
    """
    target = lang if lang and lang in SUPPORTED_LOCALES else DEFAULT_LOCALE
    
    # Try target locale first
    translations = _load_locale(target)
    result = _get_nested(translations, key)
    
    # Fallback chain if not found
    if result is None:
        for fallback in FALLBACK_CHAIN:
            if fallback == target:
                continue
            translations = _load_locale(fallback)
            result = _get_nested(translations, key)
            if result is not None:
                break
    
    # Return key if nothing found
    if result is None:
        return key
    
    # Format placeholders if string
    if isinstance(result, str):
        try:
            return result.format(**kwargs)
        except (KeyError, IndexError):
            return result
    
    return str(result)


def get(key: str, lang: str = None):
    """
    Get a raw value from translations by dot-separated key.

    Unlike t(), returns the original type (dict, list, etc.) without string conversion.
    Useful for accessing structured data like dropdown options.

    Args:
        key: Dot-separated path like 'botinfo.features_dict'
        lang: Target language code. Defaults to DEFAULT_LOCALE.

    Returns:
        Raw value (str, dict, list, etc.) or None if not found.

    Examples:
        >>> get('botinfo.features_dict', lang='id')
        {'cards': {'label': '...', 'desc': '...'}, ...}
    """
    target = lang if lang and lang in SUPPORTED_LOCALES else DEFAULT_LOCALE

    # Try target locale first
    translations = _load_locale(target)
    result = _get_nested(translations, key)

    # Fallback chain if not found
    if result is None:
        for fallback in FALLBACK_CHAIN:
            if fallback == target:
                continue
            translations = _load_locale(fallback)
            result = _get_nested(translations, key)
            if result is not None:
                break

    return result


def is_supported(locale: str) -> bool:
    """Check if a locale code is supported."""
    return locale in SUPPORTED_LOCALES


def get_supported_locales() -> list:
    """Get list of all supported locale codes."""
    return SUPPORTED_LOCALES.copy()


def get_locale_name(locale: str) -> str:
    """Get human-readable name for a locale code."""
    names = {
        "id": "Bahasa Indonesia",
        "en": "English",
        "pt": "Português",
        "es": "Español",
        "de": "Deutsch",
    }
    return names.get(locale, locale)


def clear_cache():
    """Clear translation cache (useful for development/hot-reload)."""
    global _translations_cache
    with _load_lock:
        _translations_cache = {}


# Smoke test when run directly
if __name__ == "__main__":
    # Clear cache to ensure fresh load
    clear_cache()
    
    print("🧪 i18n smoke test:")
    print(f"  supported: {get_supported_locales()}")
    print()
    
    # Test 1: ID lookup
    print(f"  [id] tarot.spread_unknown:")
    print(f"    {t('tarot.spread_unknown', lang='id')[:80]}")
    print()
    
    # Test 2: EN specific
    print(f"  [en] tarot.spread_unknown:")
    print(f"    {t('tarot.spread_unknown', lang='en')[:80]}")
    print()
    
    # Test 3: ID-specific key (not in EN)
    print(f"  [id] tarot.spread_menu_title:")
    print(f"    {t('tarot.spread_menu_title', lang='id')}")
    print()
    
    # Test 4: EN-specific key
    print(f"  [en] tarot.spread_menu_title:")
    print(f"    {t('tarot.spread_menu_title', lang='en')}")
    print()
    
    # Test 5: Placeholder
    print(f"  [en] cooldown.message with wait=60s:")
    print(f"    {t('cooldown.message', lang='en', wait='60s')}")
    print()
    
    # Test 6: Missing key (graceful)
    print(f"  [id] nonexistent.key:")
    print(f"    {t('nonexistent.key', lang='id')}")
    print()
    
    # Test 7: Unsupported locale
    print(f"  [fr] tarot.spread_menu_title (unsupported):")
    print(f"    {t('tarot.spread_menu_title', lang='fr')}")
    print()
    
    # Test 8: ID-only key (no EN equivalent)
    print(f"  [en] tarot.saved_to_history (ID-only, should fall back):")
    print(f"    {t('tarot.saved_to_history', lang='en', reading_id='ABCD1234')}")
    print()
    
    # Test 9: Aimodel with placeholder
    print(f"  [en] aimodel.current with model=claude-sonnet-4.5:")
    print(f"    {t('aimodel.current', lang='en', model='claude-sonnet-4.5')}")
    print()
    
    # Test 10: Insight with multiple placeholders
    print(f"  [en] insight.statistics_desc:")
    print(f"    {t('insight.statistics_desc', lang='en', total=15, spreads=4, unique=20)}")
    print()
    
    print("✅ bot_i18n module loaded successfully")