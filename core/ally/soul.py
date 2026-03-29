"""
SOUL.md — the ally agent's identity, purpose, and daily notes.

Located at ~/.amini/soul.md. Written in Markdown, read verbatim before every
ally agent response so the agent always has a stable sense of self and mission.

The owner writes and customises the section framework. The Ally writes the
section content. Two template states:
    SEARCHING — no owner yet; the device is looking for its person.
    SERVING   — owner established; purpose-driven companion.

Section operations (add / remove / reorder / update) delegate to
SoulSectionManager so that any heading level is supported and the document
structure is always well-formed.
"""

import json
import logging
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from core.ally.soul_section_manager import SoulSectionManager

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

    Section operations (update, add, remove, reorder) delegate to
    SoulSectionManager for robust heading-aware manipulation.

    After every write that modifies sections, a lightweight metadata record
    is written to soul_update_path so the web UI can surface what changed.

    Usage::

        soul = SoulManager(paths)
        content = soul.read(has_owner=True)   # for system prompt injection
        soul.create_for_owner("Alice", "Help me stay organised and encouraged.")
        soul.update_section("Purpose", "New purpose text.")
        soul.add_section("Growth Notes", "First growth note.", after="Purpose")
        headings = soul.get_headings()
    """

    def __init__(self, paths: "AmiPaths"):
        self._path = paths.soul_path
        self._update_path = paths.soul_update_path
        self._ssm = SoulSectionManager()

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
        if not has_owner:
            return _SEARCHING_SOUL
        return _SERVING_SOUL_TEMPLATE.format(
            owner_name="[unknown]",
            established_date="[unknown]",
            purpose="[not yet defined]",
        )

    def exists(self) -> bool:
        return self._path.exists()

    def get_headings(self) -> list[str]:
        """Return the ordered list of section headings currently in soul.md."""
        return self._ssm.list_headings(self._ssm.parse(self.read()))

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

    def write_raw(self, content: str) -> None:
        """Overwrite soul.md with arbitrary content (for user edits via CLI)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(content)

    # ------------------------------------------------------------------
    # Section operations (delegate to SoulSectionManager)
    # ------------------------------------------------------------------

    def update_section(self, heading: str, content: str) -> None:
        """Update (or create) a named section with new content."""
        sections = self._ssm.parse(self.read())
        sections = self._ssm.update(sections, heading, content)
        self._write_sections(sections, changed=[heading], operation="update")

    def add_section(
        self,
        heading: str,
        content: str,
        level: int = 2,
        after: Optional[str] = None,
        position: Optional[int] = None,
    ) -> None:
        """Insert a new section. See SoulSectionManager.add for positioning rules."""
        sections = self._ssm.parse(self.read())
        sections = self._ssm.add(sections, heading, content, level=level, after=after, position=position)
        self._write_sections(sections, changed=[heading], operation="add")

    def remove_section(self, heading: str) -> None:
        """Remove a named section. No-op if the section does not exist."""
        sections = self._ssm.parse(self.read())
        sections = self._ssm.remove(sections, heading)
        self._write_sections(sections, changed=[heading], operation="remove")

    def reorder_sections(self, new_order: list[str]) -> None:
        """Reorder sections according to new_order. Unmentioned sections go to end."""
        sections = self._ssm.parse(self.read())
        sections = self._ssm.reorder(sections, new_order)
        self._write_sections(sections, changed=new_order, operation="reorder")

    def append_to_section(self, heading: str, line: str, level: int = 2) -> None:
        """
        Append a single line to an existing section's content.

        If the section does not exist it is created. Used by EvalDay for the
        nightly lightweight journal snapshot headline append (no LLM call).
        """
        sections = self._ssm.parse(self.read())
        sections = self._ssm.append_line(sections, heading, line, level=level)
        self._write_sections(sections, changed=[heading], operation="append")

    # ------------------------------------------------------------------
    # Legacy helpers (kept for backward compatibility)
    # ------------------------------------------------------------------

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
            updated = current + header
        else:
            updated = current + "\n## Daily Notes\n" + header

        self._path.write_text(updated)
        logger.info("Appended daily notes to soul.md for %s", note_date.isoformat())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write_sections(
        self,
        sections: list,
        changed: list[str],
        operation: str,
    ) -> None:
        """Serialize sections to soul.md and record the update metadata."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(self._ssm.serialize(sections))
        self._record_update(changed, operation)
        logger.info("SoulManager: %s section(s) %s", operation, changed)

    def _record_update(self, sections_changed: list[str], operation: str) -> None:
        """Write soul_update.json with metadata about the last modification."""
        data = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "sections_changed": sections_changed,
            "operation": operation,
        }
        try:
            self._update_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._update_path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp, self._update_path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as exc:
            logger.warning("SoulManager: could not write soul_update.json: %s", exc)

    def read_last_update(self) -> Optional[dict]:
        """Return the last soul update metadata dict, or None if no update recorded."""
        if not self._update_path.exists():
            return None
        try:
            return json.loads(self._update_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
