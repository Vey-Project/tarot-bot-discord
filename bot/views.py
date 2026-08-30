"""Discord UI Views (dropdown menus) for botinfo and help."""

from __future__ import annotations

import discord
import discord.ui as _discord_ui

from bot_i18n import get as _get, t as _

# Discord SelectOption.description is capped at 100 chars and the API rejects
# longer values with HTTP 400 — features_dict.<key>.short is human-authored
# text and easily blows past the limit. Truncate defensively rather than
# trust every locale.
_DISCORD_SELECT_DESC_MAX = 100


def _clip(text: str, limit: int = _DISCORD_SELECT_DESC_MAX) -> str:
    """Trim ``text`` to fit Discord's SelectOption.description cap."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"


class FeatureView(_discord_ui.View):
    """Dropdown menu showing all bot features. Users pick one to see details."""

    def __init__(self, language: str, cog, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.language = language
        self.cog = cog

        features_dict = _get("botinfo.features_dict", lang=language)
        picker_short = _("botinfo.feature_picker_short", lang=language)

        options = []
        for key, ftr in features_dict.items():
            options.append(
                discord.SelectOption(
                    label=ftr["label"],
                    description=_clip(ftr.get("short") or ftr.get("desc", "")[:100]),
                    value=key,
                    emoji=None,
                )
            )

        self.select = _discord_ui.Select(
            placeholder=picker_short,
            options=options,
            min_values=1,
            max_values=1,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction):
        key = self.select.values[0]
        features_dict = _get("botinfo.features_dict", lang=self.language)
        ftr = features_dict.get(key)

        if not ftr:
            await interaction.response.send_message(
                _("botinfo.feature_not_found", lang=self.language),
                ephemeral=True,
            )
            return

        title_template = _("botinfo.feature_detail_title", lang=self.language)
        detail_embed = discord.Embed(
            title=title_template.format(name=ftr["label"]),
            description=ftr["desc"],
            color=0x9b59b6,
        )
        await interaction.response.send_message(embed=detail_embed, ephemeral=True)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class HelpView(_discord_ui.View):
    """Dropdown menu for !help. Users pick a category, see its items as detail embed."""

    def __init__(self, language: str, cog, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.language = language
        self.cog = cog

        cat_dict = _get("help.category_dict", lang=language)
        picker_short = _("help.category_picker_short", lang=language)

        options = []
        for key, cat in cat_dict.items():
            count = len(cat["items"])
            opts_desc = {
                "id": f"{count} item",
                "en": f"{count} items",
                "pt": f"{count} itens",
                "es": f"{count} elementos",
                "de": f"{count} Elemente",
            }.get(language, f"{count} items")
            options.append(
                discord.SelectOption(
                    label=cat["label"],
                    description=opts_desc,
                    value=key,
                    emoji=None,
                )
            )

        self.select = _discord_ui.Select(
            placeholder=picker_short,
            options=options,
            min_values=1,
            max_values=1,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction):
        key = self.select.values[0]
        cat_dict = _get("help.category_dict", lang=self.language)
        cat = cat_dict.get(key)

        if not cat:
            await interaction.response.send_message(
                _("help.category_not_found", lang=self.language),
                ephemeral=True,
            )
            return

        title_template = _("help.category_detail_title", lang=self.language)
        lines = [f"• `{item['name']}` — {item['desc']}" for item in cat["items"]]
        value = "\n".join(lines)
        if len(value) > 1024:
            value = value[:1020] + "\n…"

        detail_embed = discord.Embed(
            title=title_template.format(name=cat["label"]),
            description=value,
            color=0x9b59b6,
        )
        await interaction.response.send_message(embed=detail_embed, ephemeral=True)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True