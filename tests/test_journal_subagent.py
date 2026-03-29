"""Unit tests for agents/subagents/ally/journal_subagent.py"""

import json
import pytest
from unittest.mock import MagicMock

from core.ally.journal_manager import JournalEntry


@pytest.fixture
def journal_manager(tmp_path):
    from core.ally.journal_manager import JournalManager
    paths = MagicMock()
    paths.ally_journal_dir = tmp_path / "journal"
    return JournalManager(paths)


# ---------------------------------------------------------------------------
# JournalWriteTool
# ---------------------------------------------------------------------------

class TestJournalWriteTool:
    def test_writes_entry(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalWriteTool
        tool = JournalWriteTool(journal_manager)
        result = tool.execute(
            date="2026-03-24",
            summary="A reflective day.",
            topics='["work", "family"]',
            key_events='["finished project"]',
            emotional_tone="calm",
            action_items='["follow up"]',
        )
        assert "2026-03-24" in result
        entry = journal_manager.read_date("2026-03-24")
        assert entry is not None
        assert entry.summary == "A reflective day."
        assert entry.topics == ["work", "family"]
        assert entry.emotional_tone == "calm"

    def test_handles_missing_optional_fields(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalWriteTool
        tool = JournalWriteTool(journal_manager)
        tool.execute(date="2026-03-25", summary="Minimal entry.")
        entry = journal_manager.read_date("2026-03-25")
        assert entry is not None
        assert entry.topics == []

    def test_malformed_topics_json_fallback(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalWriteTool
        tool = JournalWriteTool(journal_manager)
        # Non-JSON string — should fall back gracefully
        tool.execute(date="2026-03-26", summary="Test.", topics="work and family")
        entry = journal_manager.read_date("2026-03-26")
        assert entry is not None
        assert isinstance(entry.topics, list)


# ---------------------------------------------------------------------------
# JournalReadTool
# ---------------------------------------------------------------------------

class TestJournalReadTool:
    def setup_entries(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalWriteTool
        tool = JournalWriteTool(journal_manager)
        tool.execute(date="2026-03-01", summary="March 1st.")
        tool.execute(date="2026-03-15", summary="March 15th.")
        tool.execute(date="2026-03-24", summary="March 24th.")

    def test_read_single_date(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalReadTool, JournalWriteTool
        JournalWriteTool(journal_manager).execute(date="2026-03-24", summary="Test summary.")
        result = JournalReadTool(journal_manager).execute(date="2026-03-24")
        assert "Test summary." in result
        assert "2026-03-24" in result

    def test_read_missing_date_message(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalReadTool
        result = JournalReadTool(journal_manager).execute(date="2000-01-01")
        assert "No journal entry found" in result

    def test_read_last_n(self, journal_manager):
        self.setup_entries(journal_manager)
        from agents.subagents.ally.journal_subagent import JournalReadTool
        result = JournalReadTool(journal_manager).execute(last_n=2)
        assert "March 24th." in result
        assert "March 15th." in result
        assert "March 1st." not in result

    def test_read_range(self, journal_manager):
        self.setup_entries(journal_manager)
        from agents.subagents.ally.journal_subagent import JournalReadTool
        result = JournalReadTool(journal_manager).execute(
            start_date="2026-03-01", end_date="2026-03-15"
        )
        assert "March 1st." in result
        assert "March 15th." in result
        assert "March 24th." not in result

    def test_no_params_returns_instructions(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalReadTool
        result = JournalReadTool(journal_manager).execute()
        assert "Provide" in result


# ---------------------------------------------------------------------------
# JournalSummaryTool
# ---------------------------------------------------------------------------

class TestJournalSummaryTool:
    def test_returns_metadata_without_summary(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalWriteTool, JournalSummaryTool
        JournalWriteTool(journal_manager).execute(
            date="2026-03-24",
            summary="Secret prose.",
            topics='["work"]',
            emotional_tone="focused",
        )
        result = JournalSummaryTool(journal_manager).execute(last_n=1)
        assert "Secret prose." not in result
        assert "work" in result
        assert "focused" in result

    def test_no_entries_returns_message(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalSummaryTool
        result = JournalSummaryTool(journal_manager).execute(last_n=10)
        assert "No journal entries" in result

    def test_respects_last_n(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalWriteTool, JournalSummaryTool
        for d in ["2026-03-01", "2026-03-02", "2026-03-03"]:
            JournalWriteTool(journal_manager).execute(date=d, summary="Day.", topics=f'["{d}"]')
        result = JournalSummaryTool(journal_manager).execute(last_n=2)
        assert "2026-03-01" not in result
        assert "2026-03-03" in result

    def test_includes_header_count(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalWriteTool, JournalSummaryTool
        JournalWriteTool(journal_manager).execute(date="2026-03-24", summary="Day.")
        result = JournalSummaryTool(journal_manager).execute(last_n=100)
        assert "1 entries" in result or "last 1" in result


# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------

class TestToolSchema:
    def test_journal_write_schema(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalWriteTool
        schema = JournalWriteTool(journal_manager).to_llm_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "journal_write"
        req = schema["function"]["parameters"]["required"]
        assert "date" in req and "summary" in req

    def test_journal_read_no_required(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalReadTool
        schema = JournalReadTool(journal_manager).to_llm_schema()
        req = schema["function"]["parameters"].get("required", [])
        assert req == []

    def test_journal_summary_schema(self, journal_manager):
        from agents.subagents.ally.journal_subagent import JournalSummaryTool
        schema = JournalSummaryTool(journal_manager).to_llm_schema()
        assert schema["function"]["name"] == "journal_summary"
