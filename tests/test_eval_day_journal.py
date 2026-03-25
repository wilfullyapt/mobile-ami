"""Unit tests for EvalDay journal flow (nightly append vs reorganize branching)."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from core.eval_day import EvalDay


@pytest.fixture
def paths(tmp_path):
    p = MagicMock()
    p.conversations_dir = tmp_path / "conversations"
    p.memory_dir = tmp_path / "memory"
    p.eval_marker_path = tmp_path / ".last_eval"
    p.ally_notes_dir = tmp_path / "notes"
    p.journal_reorg_marker_path = tmp_path / ".last_journal_reorg"
    p.conversations_dir.mkdir()
    p.memory_dir.mkdir()
    p.ally_notes_dir.mkdir()
    return p


@pytest.fixture
def ally_config():
    return {
        "eval_day_time": "03:00",
        "journal_summary_last_n": 10,
        "soul_reorganize_interval_days": 30,
        "journal_snapshot_section": "Journal Entry Snapshot",
    }


@pytest.fixture
def soul_manager():
    return MagicMock()


@pytest.fixture
def ally_agent():
    agent = MagicMock()
    agent._journal_manager = MagicMock()
    return agent


@pytest.fixture
def eval_day(paths, soul_manager, ally_config, ally_agent):
    return EvalDay(
        paths=paths,
        orchestrator=MagicMock(),
        soul_manager=soul_manager,
        ally_config=ally_config,
        ally_agent=ally_agent,
    )


# ---------------------------------------------------------------------------
# _is_reorganize_day
# ---------------------------------------------------------------------------

class TestIsReorganizeDay:
    def test_true_when_no_marker(self, eval_day, paths):
        assert eval_day._is_reorganize_day(date(2026, 3, 24)) is True

    def test_false_when_recently_reorganized(self, eval_day, paths):
        paths.journal_reorg_marker_path.write_text("2026-03-10")
        # 14 days ago, interval is 30
        assert eval_day._is_reorganize_day(date(2026, 3, 24)) is False

    def test_true_when_overdue(self, eval_day, paths):
        paths.journal_reorg_marker_path.write_text("2026-02-01")
        # 51 days ago, interval is 30
        assert eval_day._is_reorganize_day(date(2026, 3, 24)) is True

    def test_true_when_marker_corrupted(self, eval_day, paths):
        paths.journal_reorg_marker_path.write_text("not-a-date")
        assert eval_day._is_reorganize_day(date(2026, 3, 24)) is True


# ---------------------------------------------------------------------------
# _append_journal_headline
# ---------------------------------------------------------------------------

class TestAppendJournalHeadline:
    def test_appends_headline_when_entry_exists(self, eval_day, soul_manager, ally_agent):
        from core.ally.journal_manager import JournalEntry
        entry = JournalEntry(
            date="2026-03-24",
            summary="Today was good.",
            topics=["work", "family"],
        )
        ally_agent._journal_manager.read_date.return_value = entry

        eval_day._append_journal_headline(date(2026, 3, 24), "Journal Entry Snapshot")

        soul_manager.append_to_section.assert_called_once()
        args = soul_manager.append_to_section.call_args
        assert "2026-03-24" in args[0][1]
        assert "work" in args[0][1]

    def test_no_op_when_no_entry(self, eval_day, soul_manager, ally_agent):
        ally_agent._journal_manager.read_date.return_value = None
        eval_day._append_journal_headline(date(2026, 3, 24), "Journal Entry Snapshot")
        soul_manager.append_to_section.assert_not_called()

    def test_no_op_when_no_ally_agent(self, paths, soul_manager, ally_config):
        ed = EvalDay(
            paths=paths,
            orchestrator=MagicMock(),
            soul_manager=soul_manager,
            ally_config=ally_config,
            ally_agent=None,
        )
        # Should not raise
        ed._append_journal_headline(date(2026, 3, 24), "Journal Entry Snapshot")
        soul_manager.append_to_section.assert_not_called()


# ---------------------------------------------------------------------------
# _update_journal_snapshot branching
# ---------------------------------------------------------------------------

class TestUpdateJournalSnapshot:
    def test_calls_reorganize_on_reorganize_day(self, eval_day, paths, ally_agent):
        # No marker → first run → reorganize
        eval_day._update_journal_snapshot(date(2026, 3, 24))
        ally_agent.run_journal_reorganize.assert_called_once_with(
            snapshot_section="Journal Entry Snapshot",
            last_n=10,
        )

    def test_writes_reorg_marker_after_reorganize(self, eval_day, paths, ally_agent):
        eval_day._update_journal_snapshot(date(2026, 3, 24))
        assert paths.journal_reorg_marker_path.read_text() == "2026-03-24"

    def test_calls_append_on_non_reorganize_day(self, eval_day, paths, ally_agent):
        # Mark recent reorg so we're not due yet
        paths.journal_reorg_marker_path.write_text("2026-03-20")
        from core.ally.journal_manager import JournalEntry
        ally_agent._journal_manager.read_date.return_value = JournalEntry(
            date="2026-03-24", summary="Day.", topics=["work"]
        )
        eval_day._update_journal_snapshot(date(2026, 3, 24))
        ally_agent.run_journal_reorganize.assert_not_called()


# ---------------------------------------------------------------------------
# _run_journal_session
# ---------------------------------------------------------------------------

class TestRunJournalSession:
    def test_calls_ally_agent_run_journal_session(self, eval_day, ally_agent):
        eval_day._run_journal_session(
            conversations=[{"user": "hello", "agent": "ally"}],
            summary="Quiet day.",
            target_date=date(2026, 3, 24),
        )
        ally_agent.run_journal_session.assert_called_once()
        kwargs = ally_agent.run_journal_session.call_args
        assert kwargs[1]["date_str"] == "2026-03-24"

    def test_no_op_when_ally_agent_missing_method(self, paths, soul_manager, ally_config):
        """If ally_agent doesn't have run_journal_session, should not raise."""
        agent_without_method = MagicMock(spec=[])
        ed = EvalDay(
            paths=paths,
            orchestrator=MagicMock(),
            soul_manager=soul_manager,
            ally_config=ally_config,
            ally_agent=agent_without_method,
        )
        ed._run_journal_session([], "", date(2026, 3, 24))  # must not raise
