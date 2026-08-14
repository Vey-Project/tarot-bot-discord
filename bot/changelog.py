"""Lightweight parser for CHANGELOG.md in Keep a Changelog format.

We avoid external Markdown libraries on purpose: the bot already has a tiny
footprint and a CHANGELOG file has a very predictable structure. A few
regex passes are enough to pull out:

- version: ``1.1.0``
- date:    ``2026-08-14``  (optional, omitted entries are tolerated)
- sections: ``Added`` / ``Changed`` / ``Deprecated`` / ``Removed`` /
  ``Fixed`` / ``Security`` — bullets underneath each section

Output: a list of dicts, newest first::

    [
      {"version": "1.1.0", "date": "2026-08-14",
       "sections": {"Added": ["...", "..."], "Fixed": ["..."]}},
      ...
    ]

This module never raises — file not found, malformed lines, encoding
errors all degrade to empty results so the bot can still answer the
``/changelog`` command with a sensible fallback message.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

_VERSION_RE = re.compile(
    r"^##\s*\[(?P<version>[^\]]+)\]"
    r"(?:\s*-\s*(?P<date>\d{4}-\d{2}-\d{2}))?\s*$"
)
_SECTION_RE = re.compile(r"^###\s+(?P<name>[A-Za-z]+)\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(?P<text>.+?)\s*$")

_KNOWN_SECTIONS = {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}


def _strip_markdown(text: str) -> str:
    """Light cleanup for embed display.

    We don't try to render full Markdown — Discord already does. We just
    drop the surrounding emphasis markers so bullets read nicely when
    joined with newlines.
    """
    # Strip trailing whitespace and collapse internal newlines.
    return " ".join(text.split())


def parse_changelog(path: Optional[Path] = None) -> List[Dict]:
    """Parse a Keep-a-Changelog file. Returns newest-first list.

    Args:
        path: Path to the CHANGELOG.md file. If ``None``, defaults to
            ``<project-root>/CHANGELOG.md``.

    Returns:
        List of release dicts. Empty list on any failure.
    """
    if path is None:
        # <repo>/bot/changelog.py  →  <repo>/CHANGELOG.md
        path = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    releases: List[Dict] = []
    current: Optional[Dict] = None
    current_section: Optional[str] = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        version_match = _VERSION_RE.match(line)
        if version_match:
            current = {
                "version": version_match.group("version").strip(),
                "date": (version_match.group("date") or "").strip() or None,
                "sections": {},
            }
            current_section = None
            releases.append(current)
            continue

        if current is None:
            # Above the first release heading (header / preamble). Skip.
            continue

        section_match = _SECTION_RE.match(line)
        if section_match:
            section_name = section_match.group("name").strip()
            current_section = section_name if section_name in _KNOWN_SECTIONS else None
            continue

        bullet_match = _BULLET_RE.match(line)
        if bullet_match and current_section is not None:
            bullet = _strip_markdown(bullet_match.group("text"))
            if bullet:
                current["sections"].setdefault(current_section, []).append(bullet)

    return releases


def latest_releases(count: int = 3) -> List[Dict]:
    """Return the most recent N releases from the changelog.

    Args:
        count: Maximum number of releases to return.

    Returns:
        Newest-first list of release dicts. Empty if no CHANGELOG.md.
    """
    releases = parse_changelog()
    if count <= 0:
        return []
    return releases[:count]