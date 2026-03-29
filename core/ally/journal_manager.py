"""
JournalManager — storage layer for Ally daily journal entries.

Each journal entry is a JSON file at::

    ~/.amini/data/ally/journal/<YYYY-MM-DD>.json

Structure::

    {
      "date": "2026-03-24",
      "written_at": "2026-03-24T03:01:45+00:00",
      "topics": ["productivity", "family"],
      "key_events": ["finished quarterly report"],
      "emotional_tone": "contemplative",
      "action_items": ["follow up with finance team"],
      "summary": "Full prose narrative written by the LLM...",
      "metadata": {
        "conversation_count": 12,
        "ambient_note_count": 8
      }
    }

``read_metadata_last_n`` omits the ``summary`` field so that scanning 100
entries stays cheap. The summary is only loaded when explicitly requested
via ``read_date`` / ``read_range`` / ``read_last_n``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JournalEntry dataclass
# ---------------------------------------------------------------------------

@dataclass
class JournalEntry:
    date: str                            # ISO date "YYYY-MM-DD"
    summary: str                         # LLM-written prose narrative
    topics: list[str] = field(default_factory=list)
    key_events: list[str] = field(default_factory=list)
    emotional_tone: str = ""
    action_items: list[str] = field(default_factory=list)
    written_at: str = ""                 # ISO datetime; auto-filled on write
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "JournalEntry":
        return cls(
            date=data.get("date", ""),
            summary=data.get("summary", ""),
            topics=data.get("topics", []),
            key_events=data.get("key_events", []),
            emotional_tone=data.get("emotional_tone", ""),
            action_items=data.get("action_items", []),
            written_at=data.get("written_at", ""),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# JournalManager
# ---------------------------------------------------------------------------

class JournalManager:
    """
    Read and write daily journal entries.

    Parameters
    ----------
    paths:
        AmiPaths instance. Journal files live at ``paths.ally_journal_dir``.
    """

    def __init__(self, paths: "AmiPaths"):
        self._dir = paths.ally_journal_dir

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write(self, entry: JournalEntry) -> None:
        """
        Atomically write a journal entry to disk.

        ``entry.written_at`` is set to the current UTC time if empty.
        Overwrites any existing entry for the same date.
        """
        if not entry.written_at:
            entry.written_at = datetime.now(timezone.utc).isoformat()

        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._dir / f"{entry.date}.json"
        self._atomic_write(target, entry.to_dict())
        logger.info("JournalManager: wrote entry for %s", entry.date)

    # ------------------------------------------------------------------
    # Read — full entries (include summary)
    # ------------------------------------------------------------------

    def read_date(self, date: str) -> Optional[JournalEntry]:
        """Return the journal entry for the given ISO date, or None."""
        path = self._dir / f"{date}.json"
        return self._load_entry(path)

    def read_range(self, start: str, end: str) -> list[JournalEntry]:
        """
        Return all entries between ``start`` and ``end`` (inclusive, ISO dates).

        Results are sorted oldest-first.
        """
        entries = []
        for path in self._sorted_paths():
            stem = path.stem  # YYYY-MM-DD
            if start <= stem <= end:
                entry = self._load_entry(path)
                if entry:
                    entries.append(entry)
        return entries

    def read_last_n(self, n: int) -> list[JournalEntry]:
        """Return the *n* most recent journal entries, newest-first."""
        paths = self._sorted_paths()[-n:]
        entries = []
        for path in reversed(paths):
            entry = self._load_entry(path)
            if entry:
                entries.append(entry)
        return entries

    # ------------------------------------------------------------------
    # Read — metadata only (exclude summary for efficiency)
    # ------------------------------------------------------------------

    def read_metadata_last_n(self, n: int) -> list[dict]:
        """
        Return metadata dicts for the *n* most recent entries, newest-first.

        The ``summary`` field is excluded so that scanning many entries
        stays cheap. Each dict contains: date, written_at, topics,
        key_events, emotional_tone, action_items, metadata.
        """
        paths = self._sorted_paths()[-n:]
        result = []
        for path in reversed(paths):
            data = self._load_raw(path)
            if data is not None:
                data.pop("summary", None)
                result.append(data)
        return result

    def last_n_dates(self, n: int) -> list[str]:
        """Return ISO date strings for the *n* most recent entries (newest-first)."""
        return [p.stem for p in reversed(self._sorted_paths()[-n:])]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sorted_paths(self) -> list[Path]:
        """All journal JSON paths sorted oldest-first by filename (YYYY-MM-DD)."""
        if not self._dir.exists():
            return []
        return sorted(self._dir.glob("*.json"))

    def _load_entry(self, path: Path) -> Optional[JournalEntry]:
        data = self._load_raw(path)
        if data is None:
            return None
        try:
            return JournalEntry.from_dict(data)
        except Exception as exc:
            logger.warning("JournalManager: bad entry %s: %s", path, exc)
            return None

    def _load_raw(self, path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("JournalManager: could not read %s: %s", path, exc)
            return None

    @staticmethod
    def _atomic_write(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
