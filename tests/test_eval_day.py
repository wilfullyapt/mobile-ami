"""Unit tests for core/eval_day.py"""

import json
import pytest
from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from core.eval_day import EvalDay
from core.ami_paths import AmiPaths
from core.soul import SoulManager


@pytest.fixture
def paths(tmp_path):
    p = AmiPaths(root=str(tmp_path / "amini"))
    p.ensure_dirs()
    return p


@pytest.fixture
def soul(paths):
    s = SoulManager(paths)
    s.create_for_owner("Alice")
    return s


def _make_llm(response="- Alice talked about work.\n- She plans to exercise."):
    llm = MagicMock()
    llm.chat.return_value = response
    return llm


def _make_orchestrator(llm=None):
    from core.model_registry import ModelRole
    orch = MagicMock()
    _llm = llm or _make_llm()
    orch.get.return_value = _llm
    return orch


def _write_conversation(paths, agent="qa", user="Hello", response="Hi!", ts_prefix=None):
    """Write a fake conversation log file under conversations/<agent>/."""
    ts = ts_prefix or date.today().isoformat()
    agent_dir = paths.conversations_dir / agent
    agent_dir.mkdir(parents=True, exist_ok=True)
    log_path = agent_dir / f"{ts}_test.json"
    log_path.write_text(json.dumps([{
        "timestamp": f"{ts}T12:00:00",
        "user": user,
        "response": response,
    }]))
    return log_path


class TestEvalDayRunNow:
    def test_returns_none_when_no_conversations(self, paths, soul):
        orch = _make_orchestrator()
        ed = EvalDay(paths, orch, soul, {"eval_day_time": "03:00"})
        result = ed.run_now()
        assert result is None

    def test_returns_summary_when_conversations_exist(self, paths, soul):
        _write_conversation(paths)
        orch = _make_orchestrator()
        ed = EvalDay(paths, orch, soul, {"eval_day_time": "03:00"})
        result = ed.run_now()
        assert result is not None
        assert "summary" in result
        assert result["date"] == date.today().isoformat()

    def test_saves_memory_json(self, paths, soul):
        _write_conversation(paths)
        orch = _make_orchestrator()
        ed = EvalDay(paths, orch, soul, {"eval_day_time": "03:00"})
        ed.run_now()
        mem_files = list(paths.memory_dir.glob("*.json"))
        assert len(mem_files) == 1

    def test_writes_eval_marker(self, paths, soul):
        orch = _make_orchestrator()
        ed = EvalDay(paths, orch, soul, {"eval_day_time": "03:00"})
        ed.run_now()
        assert paths.eval_marker_path.exists()

    def test_does_not_update_soul_by_default(self, paths, soul):
        _write_conversation(paths)
        orch = _make_orchestrator()
        ed = EvalDay(paths, orch, soul, {"eval_day_time": "03:00", "update_soul_on_eval": False})
        soul_before = paths.soul_path.read_text()
        ed.run_now()
        assert paths.soul_path.read_text() == soul_before

    def test_updates_soul_when_flag_set(self, paths, soul):
        _write_conversation(paths)
        orch = _make_orchestrator(_make_llm("- Great day."))
        ed = EvalDay(paths, orch, soul, {"eval_day_time": "03:00", "update_soul_on_eval": True})
        ed.run_now()
        content = paths.soul_path.read_text()
        assert "Great day." in content

    def test_target_date_filters_conversations(self, paths, soul):
        # Write one for today and one for yesterday
        _write_conversation(paths, ts_prefix="2026-01-01")
        _write_conversation(paths, ts_prefix=date.today().isoformat())
        orch = _make_orchestrator()
        ed = EvalDay(paths, orch, soul, {})
        result = ed.run_now(target_date=date.today())
        # Should find today's conversation (at minimum)
        assert result is not None


class TestEvalDayIsOverdue:
    def test_overdue_when_no_marker_and_conversations_exist(self, paths, soul):
        _write_conversation(paths)
        orch = _make_orchestrator()
        ed = EvalDay(paths, orch, soul, {})
        assert ed._is_overdue() is True

    def test_not_overdue_when_no_conversations(self, paths, soul):
        orch = _make_orchestrator()
        ed = EvalDay(paths, orch, soul, {})
        assert ed._is_overdue() is False

    def test_not_overdue_when_marker_recent(self, paths, soul):
        _write_conversation(paths)
        orch = _make_orchestrator()
        ed = EvalDay(paths, orch, soul, {})
        # Write a recent marker
        paths.eval_marker_path.write_text(datetime.now(timezone.utc).isoformat())
        assert ed._is_overdue() is False

    def test_overdue_when_marker_is_old(self, paths, soul):
        _write_conversation(paths)
        orch = _make_orchestrator()
        ed = EvalDay(paths, orch, soul, {})
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        paths.eval_marker_path.write_text(old_time)
        assert ed._is_overdue() is True


class TestEvalDayParseTime:
    def test_valid_time(self, paths, soul):
        orch = _make_orchestrator()
        ed = EvalDay(paths, orch, soul, {"eval_day_time": "14:30"})
        assert ed._parse_eval_time() == (14, 30)

    def test_invalid_time_falls_back_to_3am(self, paths, soul):
        orch = _make_orchestrator()
        ed = EvalDay(paths, orch, soul, {"eval_day_time": "bad"})
        assert ed._parse_eval_time() == (3, 0)
