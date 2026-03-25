"""Unit tests for core/ally/journal_manager.py"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from core.ally.journal_manager import JournalManager, JournalEntry


@pytest.fixture
def tmp_paths(tmp_path):
    paths = MagicMock()
    paths.ally_journal_dir = tmp_path / "journal"
    return paths


@pytest.fixture
def manager(tmp_paths):
    return JournalManager(tmp_paths)


def make_entry(date="2026-03-24", summary="Today was good.", **kwargs) -> JournalEntry:
    return JournalEntry(
        date=date,
        summary=summary,
        topics=kwargs.get("topics", ["work"]),
        key_events=kwargs.get("key_events", ["finished report"]),
        emotional_tone=kwargs.get("emotional_tone", "content"),
        action_items=kwargs.get("action_items", ["follow up"]),
    )


# ---------------------------------------------------------------------------
# write + read_date
# ---------------------------------------------------------------------------

class TestWriteRead:
    def test_write_creates_file(self, manager, tmp_paths):
        entry = make_entry("2026-03-24")
        manager.write(entry)
        assert (tmp_paths.ally_journal_dir / "2026-03-24.json").exists()

    def test_write_sets_written_at(self, manager):
        entry = make_entry()
        assert entry.written_at == ""
        manager.write(entry)
        assert entry.written_at != ""

    def test_read_date_returns_entry(self, manager):
        entry = make_entry("2026-03-24", summary="Test summary.")
        manager.write(entry)
        loaded = manager.read_date("2026-03-24")
        assert loaded is not None
        assert loaded.summary == "Test summary."
        assert loaded.date == "2026-03-24"

    def test_read_date_missing_returns_none(self, manager):
        assert manager.read_date("2000-01-01") is None

    def test_write_overwrites_existing(self, manager):
        manager.write(make_entry("2026-03-24", summary="First."))
        manager.write(make_entry("2026-03-24", summary="Second."))
        loaded = manager.read_date("2026-03-24")
        assert loaded.summary == "Second."

    def test_write_preserves_metadata_fields(self, manager):
        entry = make_entry(
            "2026-03-24",
            topics=["a", "b"],
            key_events=["event1"],
            emotional_tone="calm",
            action_items=["act1"],
        )
        manager.write(entry)
        loaded = manager.read_date("2026-03-24")
        assert loaded.topics == ["a", "b"]
        assert loaded.key_events == ["event1"]
        assert loaded.emotional_tone == "calm"
        assert loaded.action_items == ["act1"]

    def test_atomic_write_no_partial_file(self, manager, tmp_paths):
        """File should not exist in a half-written state."""
        entry = make_entry()
        manager.write(entry)
        path = tmp_paths.ally_journal_dir / f"{entry.date}.json"
        data = json.loads(path.read_text())
        assert "date" in data and "summary" in data


# ---------------------------------------------------------------------------
# read_range
# ---------------------------------------------------------------------------

class TestReadRange:
    def test_read_range_inclusive(self, manager):
        for d in ["2026-03-01", "2026-03-15", "2026-03-31"]:
            manager.write(make_entry(d))
        entries = manager.read_range("2026-03-01", "2026-03-15")
        dates = [e.date for e in entries]
        assert "2026-03-01" in dates
        assert "2026-03-15" in dates
        assert "2026-03-31" not in dates

    def test_read_range_empty_when_no_matches(self, manager):
        manager.write(make_entry("2026-03-24"))
        entries = manager.read_range("2025-01-01", "2025-12-31")
        assert entries == []


# ---------------------------------------------------------------------------
# read_last_n
# ---------------------------------------------------------------------------

class TestReadLastN:
    def test_read_last_n_returns_newest_first(self, manager):
        for d in ["2026-03-01", "2026-03-02", "2026-03-03"]:
            manager.write(make_entry(d, summary=f"Day {d}"))
        entries = manager.read_last_n(2)
        assert len(entries) == 2
        assert entries[0].date == "2026-03-03"
        assert entries[1].date == "2026-03-02"

    def test_read_last_n_clamps_to_available(self, manager):
        manager.write(make_entry("2026-03-01"))
        entries = manager.read_last_n(100)
        assert len(entries) == 1

    def test_read_last_n_empty_dir(self, manager):
        entries = manager.read_last_n(10)
        assert entries == []


# ---------------------------------------------------------------------------
# read_metadata_last_n
# ---------------------------------------------------------------------------

class TestReadMetadata:
    def test_metadata_excludes_summary(self, manager):
        manager.write(make_entry("2026-03-24", summary="Secret prose."))
        meta_list = manager.read_metadata_last_n(1)
        assert len(meta_list) == 1
        assert "summary" not in meta_list[0]

    def test_metadata_includes_topics(self, manager):
        manager.write(make_entry("2026-03-24", topics=["family", "work"]))
        meta = manager.read_metadata_last_n(1)[0]
        assert meta["topics"] == ["family", "work"]

    def test_metadata_newest_first(self, manager):
        for d in ["2026-03-01", "2026-03-02", "2026-03-03"]:
            manager.write(make_entry(d))
        meta_list = manager.read_metadata_last_n(3)
        assert meta_list[0]["date"] == "2026-03-03"

    def test_metadata_last_n_limits(self, manager):
        for d in ["2026-03-01", "2026-03-02", "2026-03-03"]:
            manager.write(make_entry(d))
        meta_list = manager.read_metadata_last_n(2)
        assert len(meta_list) == 2


# ---------------------------------------------------------------------------
# last_n_dates
# ---------------------------------------------------------------------------

class TestLastNDates:
    def test_returns_dates_newest_first(self, manager):
        for d in ["2026-03-01", "2026-03-02"]:
            manager.write(make_entry(d))
        dates = manager.last_n_dates(2)
        assert dates == ["2026-03-02", "2026-03-01"]

    def test_empty_when_no_entries(self, manager):
        assert manager.last_n_dates(5) == []


# ---------------------------------------------------------------------------
# JournalEntry dataclass
# ---------------------------------------------------------------------------

class TestJournalEntry:
    def test_to_dict_from_dict_roundtrip(self):
        e = make_entry("2026-03-24", summary="Hello.")
        assert JournalEntry.from_dict(e.to_dict()).summary == "Hello."

    def test_from_dict_missing_fields_default(self):
        e = JournalEntry.from_dict({"date": "2026-03-01", "summary": "x"})
        assert e.topics == []
        assert e.emotional_tone == ""
