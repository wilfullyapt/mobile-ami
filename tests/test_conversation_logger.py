"""Tests for core/conversation_logger.py."""
import json
import tempfile
from pathlib import Path

import pytest

from core.ami_paths import AmiPaths
from core.conversation_logger import ConversationLogger


@pytest.fixture
def tmp_paths(tmp_path):
    return AmiPaths(root=str(tmp_path))


@pytest.fixture
def logger(tmp_paths):
    tmp_paths.ensure_dirs()
    return ConversationLogger(tmp_paths)


# ------------------------------------------------------------------
# log()
# ------------------------------------------------------------------

def test_log_returns_nonempty_id(logger):
    conv_id = logger.log("qa", "Hello", "Hi there")
    assert len(conv_id) > 0


def test_log_creates_file(logger, tmp_paths):
    logger.log("qa", "Hello", "Hi there")
    agent_dir = tmp_paths.conversation_agent_dir("qa")
    files = list(agent_dir.glob("*.json"))
    assert len(files) == 1


def test_log_file_contains_correct_fields(logger, tmp_paths):
    logger.log("qa", "What time is it?", "I don't know.")
    agent_dir = tmp_paths.conversation_agent_dir("qa")
    entry = json.loads(list(agent_dir.glob("*.json"))[0].read_text())
    assert entry["agent"] == "qa"
    assert entry["transcript"] == "What time is it?"
    assert entry["response"] == "I don't know."
    assert "timestamp" in entry
    assert "id" in entry


def test_log_noop_on_empty_inputs(logger, tmp_paths):
    result = logger.log("", "hello", "world")
    assert result == ""
    result = logger.log("qa", "", "world")
    assert result == ""
    result = logger.log("qa", "hello", "")
    assert result == ""
    # No files created
    assert not tmp_paths.conversations_dir.exists() or \
           len(list(tmp_paths.conversations_dir.rglob("*.json"))) == 0


def test_log_multiple_agents_creates_separate_dirs(logger, tmp_paths):
    logger.log("qa", "Q1", "A1")
    logger.log("block_timer", "Set a 5 minute timer", "Timer set!")
    assert (tmp_paths.conversation_agent_dir("qa")).exists()
    assert (tmp_paths.conversation_agent_dir("block_timer")).exists()


def test_log_multiple_entries_same_agent(logger, tmp_paths):
    logger.log("qa", "Q1", "A1")
    logger.log("qa", "Q2", "A2")
    files = list(tmp_paths.conversation_agent_dir("qa").glob("*.json"))
    assert len(files) == 2


# ------------------------------------------------------------------
# get_history()
# ------------------------------------------------------------------

def test_get_history_empty_when_no_conversations(logger):
    assert logger.get_history() == []


def test_get_history_returns_all_entries(logger):
    logger.log("qa", "Q1", "A1")
    logger.log("qa", "Q2", "A2")
    history = logger.get_history()
    assert len(history) == 2


def test_get_history_filters_by_agent(logger):
    logger.log("qa", "Q1", "A1")
    logger.log("block_timer", "Set timer", "Done")
    qa_history = logger.get_history(agent="qa")
    assert len(qa_history) == 1
    assert qa_history[0]["agent"] == "qa"


def test_get_history_sorted_newest_first(logger):
    logger.log("qa", "First", "Response 1")
    logger.log("qa", "Second", "Response 2")
    history = logger.get_history(agent="qa")
    # Newer entry should be first
    assert history[0]["transcript"] == "Second"
    assert history[1]["transcript"] == "First"


def test_get_history_respects_limit(logger):
    for i in range(10):
        logger.log("qa", f"Q{i}", f"A{i}")
    history = logger.get_history(limit=3)
    assert len(history) == 3


def test_get_history_unknown_agent_returns_empty(logger):
    logger.log("qa", "Q1", "A1")
    assert logger.get_history(agent="nonexistent") == []


# ------------------------------------------------------------------
# get_agents_with_history()
# ------------------------------------------------------------------

def test_get_agents_with_history_empty(logger):
    assert logger.get_agents_with_history() == []


def test_get_agents_with_history_lists_agents(logger):
    logger.log("qa", "Q1", "A1")
    logger.log("block_timer", "Set timer", "Done")
    agents = logger.get_agents_with_history()
    assert "qa" in agents
    assert "block_timer" in agents


def test_get_agents_with_history_sorted(logger):
    logger.log("qa", "Q1", "A1")
    logger.log("block_timer", "Set timer", "Done")
    agents = logger.get_agents_with_history()
    assert agents == sorted(agents)
