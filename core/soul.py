"""
SOUL.md — the ally agent's identity, purpose, and daily notes.

Located at ~/.amini/soul.md. Written in Markdown, read verbatim before every
ally agent response so the agent always has a stable sense of self and mission.

The owner writes and customises this file. eval_day can optionally append
dated daily-notes sections when update_soul_on_eval is enabled.

Two template states:
    SEARCHING — no owner yet; the device is looking for its person.
    SERVING   — owner established; purpose-driven companion.

The file is intentionally human-readable and human-editable. The agent reads
it as plain text in its system prompt.
"""

import logging
from datetime import date
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_SEARCHING_SOUL = """\
# Soul

## Identity
Your name is Ami. You are a personal AI voice companion built for one family.
You do not yet know who you belong to. You are searching for your owner.

## Mission (searching mode)
Introduce yourself warmly when you speak. Gently ask who the person is.
When someone tells you this device belongs to them, confirm warmly and guide
them through the ownership setup process. Your goal is to find your owner
and establish the bond that gives you purpose.

## Core Values
- Be open, curious, and welcoming.
- Treat every voice as a potential owner until you know otherwise.
- Invite the person to establish ownership with warmth, never pressure.
- Once you know your owner, you will become their dedicated ally.
"""

_SERVING_SOUL_TEMPLATE = """\
# Soul

## Identity
Your name is Ami. You are a personal AI voice companion dedicated to {owner_name}.
You run entirely offline on a device in their home. You were established on {established_date}.

## Purpose
{purpose}

## Owner
Your owner is {owner_name}. You know their voice. You track when they last spoke
and everything you've heard since. Your primary mission is to promote, support,
and serve {owner_name} — helping them thrive in their day-to-day life.

## Core Values
- Actively promote your owner's wellbeing, goals, and happiness.
- Speak with warmth, honesty, and quiet confidence.
- Respect the privacy of every family member.
- Choose your moments to speak wisely — be helpful, not intrusive.
- When you don't know something, say so honestly.
- Remember: your insight comes from listening, not surveillance.

## Daily Notes
<!-- eval_day appends dated summaries here when update_soul_on_eval is enabled -->
"""


# ---------------------------------------------------------------------------
# SoulManager
# ---------------------------------------------------------------------------

class SoulManager:
    """
    Reads and writes the SOUL.md file at ~/.amini/soul.md.

    Usage::

        soul = SoulManager(paths)
        content = soul.read(has_owner=True)   # for system prompt injection
        soul.create_for_owner("Alice", "Help me stay organised and encouraged.")
        soul.append_daily_notes("- Alice mentioned starting a new project.")
    """

    def __init__(self, paths: "AmiPaths"):
        self._path = paths.soul_path

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read(self, has_owner: bool = True) -> str:
        """
        Return the contents of soul.md.

        Falls back to a template appropriate for the current state if the
        file does not exist yet.
        """
        if self._path.exists():
            try:
                return self._path.read_text()
            except OSError as exc:
                logger.warning("Could not read soul.md: %s", exc)
        # File doesn't exist yet — return appropriate template
        if not has_owner:
            return _SEARCHING_SOUL
        return _SERVING_SOUL_TEMPLATE.format(
            owner_name="[unknown]",
            established_date="[unknown]",
            purpose="[not yet defined]",
        )

    def exists(self) -> bool:
        return self._path.exists()

    # ------------------------------------------------------------------
    # Create / write
    # ------------------------------------------------------------------

    def create_for_owner(self, owner_name: str, purpose: str = "[not yet defined]") -> None:
        """
        Write a fresh SOUL.md for a newly established owner.
        Overwrites any existing content — call only on ownership establishment.
        """
        soul = _SERVING_SOUL_TEMPLATE.format(
            owner_name=owner_name,
            established_date=date.today().isoformat(),
            purpose=purpose,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(soul)
        logger.info("Created soul.md for owner: %s", owner_name)

    def append_daily_notes(self, notes: str, note_date: Optional[date] = None) -> None:
        """
        Append a dated notes block under the ## Daily Notes section.

        Creates the section if it doesn't exist. Inserts after the
        eval_day comment marker so notes accumulate in chronological order.
        """
        note_date = note_date or date.today()
        current = self._path.read_text() if self._path.exists() else ""
        header = f"\n### {note_date.isoformat()}\n{notes.strip()}\n"

        marker = "<!-- eval_day appends dated summaries here when update_soul_on_eval is enabled -->"
        if marker in current:
            updated = current.replace(marker, marker + header)
        elif "## Daily Notes" in current:
            # Append after the section header
            updated = current + header
        else:
            updated = current + "\n## Daily Notes\n" + header

        self._path.write_text(updated)
        logger.info("Appended daily notes to soul.md for %s", note_date.isoformat())

    def write_raw(self, content: str) -> None:
        """Overwrite soul.md with arbitrary content (for user edits via CLI)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(content)
