"""Unit tests for agents/ally_agent.py"""

import pytest
from unittest.mock import MagicMock, patch
from agents.ally_agent import AllyAgent
from agents.tools.tool_registry import ToolRegistry
from core.model_registry import ModelRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm(response="Hello, I'm Ami."):
    llm = MagicMock()
    llm.chat.return_value = response
    return llm


def _make_orchestrator(llm=None):
    orch = MagicMock()
    _llm = llm or _make_llm()
    orch.get.return_value = _llm
    return orch


def _make_soul(content="# Soul\nYou are Ami."):
    soul = MagicMock()
    soul.read.return_value = content
    soul.exists.return_value = True
    return soul


def _make_owner(name="Alice", has_owner=True, secs_since_seen=30.0):
    owner = MagicMock()
    owner.has_owner = has_owner
    owner.owner_name = name if has_owner else None
    owner.seconds_since_owner_seen.return_value = secs_since_seen
    owner.record_seen = MagicMock()
    return owner


def _make_agent(llm=None, soul=None, owner=None, listener=None,
                on_owner_established=None, has_owner=True):
    orch = _make_orchestrator(llm)
    registry = ToolRegistry()
    return AllyAgent(
        orchestrator=orch,
        tool_registry=registry,
        soul_manager=soul or _make_soul(),
        owner_manager=owner or _make_owner(has_owner=has_owner),
        on_owner_established=on_owner_established,
        ally_listener=listener,
    )


# ---------------------------------------------------------------------------
# Searching mode (no owner)
# ---------------------------------------------------------------------------

class TestAllyAgentSearching:
    def test_process_returns_llm_response(self):
        agent = _make_agent(has_owner=False, llm=_make_llm("Hello there!"))
        result = agent.process("Who are you?")
        assert result == "Hello there!"

    def test_fallback_response_mentions_owner_search(self):
        agent = _make_agent(has_owner=False, llm=_make_llm(""))
        result = agent.process("hello")
        assert "owner" in result.lower() or "ami" in result.lower()

    def test_ownership_claim_fires_callback(self):
        callback = MagicMock()
        agent = _make_agent(has_owner=False, on_owner_established=callback)
        agent.process("I am Alice, this device is mine")
        callback.assert_called_once_with("Alice")

    def test_ownership_claim_with_speaker_uses_speaker_name(self):
        callback = MagicMock()
        agent = _make_agent(has_owner=False, on_owner_established=callback)
        agent.process("this device is mine", speaker="Bob")
        callback.assert_called_once_with("Bob")

    def test_ownership_claim_returns_welcome_message(self):
        agent = _make_agent(has_owner=False)
        result = agent.process("I am Jake, this device is mine")
        assert "Jake" in result or "glad" in result.lower()

    def test_register_me_pattern_triggers_claim(self):
        callback = MagicMock()
        agent = _make_agent(has_owner=False, on_owner_established=callback)
        agent.process("register me as the owner", speaker="Sam")
        callback.assert_called()

    def test_no_claim_in_normal_text(self):
        callback = MagicMock()
        agent = _make_agent(has_owner=False, on_owner_established=callback)
        agent.process("What's the weather like?")
        callback.assert_not_called()


# ---------------------------------------------------------------------------
# Serving mode (owner known)
# ---------------------------------------------------------------------------

class TestAllyAgentServing:
    def test_process_returns_llm_response(self):
        agent = _make_agent(llm=_make_llm("Good morning, Alice!"))
        result = agent.process("Good morning")
        assert result == "Good morning, Alice!"

    def test_records_seen_when_owner_speaks(self):
        owner = _make_owner(name="Alice")
        agent = _make_agent(owner=owner)
        agent.process("hello", speaker="Alice")
        owner.record_seen.assert_called_once_with("Alice")

    def test_does_not_record_seen_for_non_owner(self):
        owner = _make_owner(name="Alice")
        agent = _make_agent(owner=owner)
        agent.process("hello", speaker="Jake")  # not the owner
        owner.record_seen.assert_not_called()

    def test_soul_read_called_with_has_owner_true(self):
        soul = _make_soul()
        agent = _make_agent(soul=soul)
        agent.process("hello")
        soul.read.assert_called_with(has_owner=True)

    def test_fallback_response_when_llm_empty(self):
        agent = _make_agent(llm=_make_llm(""))
        result = agent.process("hello")
        assert "here" in result.lower()

    def test_ownership_claim_not_triggered_when_owner_exists(self):
        callback = MagicMock()
        agent = _make_agent(has_owner=True, on_owner_established=callback)
        agent.process("I am Bob, this device is mine")
        callback.assert_not_called()


# ---------------------------------------------------------------------------
# Autonomous intervention — should_intervene()
# ---------------------------------------------------------------------------

class TestShouldIntervene:
    def _make_utterance(self, text, speaker="Alice", is_owner=True, seconds_ago=10.0):
        from core.ally_listener import AmbientUtterance
        from datetime import datetime, timezone, timedelta
        utt = MagicMock(spec=AmbientUtterance)
        utt.speaker = speaker
        utt.is_owner = is_owner
        utt.text = text
        utt.seconds_ago.return_value = seconds_ago
        return utt

    def test_returns_true_when_llm_says_speak(self):
        agent = _make_agent(llm=_make_llm("SPEAK: Have you had water today, Alice?"))
        ctx = [self._make_utterance("I've been working for 3 hours")]
        should, msg = agent.should_intervene(context_override=ctx)
        assert should is True
        assert "Have you had water" in msg

    def test_returns_false_when_llm_says_silent(self):
        agent = _make_agent(llm=_make_llm("SILENT"))
        ctx = [self._make_utterance("What time is it?")]
        should, msg = agent.should_intervene(context_override=ctx)
        assert should is False
        assert msg is None

    def test_returns_false_when_no_context_and_searching(self):
        agent = _make_agent(has_owner=False)
        should, msg = agent.should_intervene(context_override=[])
        assert should is False

    def test_searching_mode_can_speak(self):
        agent = _make_agent(
            has_owner=False,
            llm=_make_llm("SPEAK: Hi there! I'm Ami, looking for my owner."),
        )
        ctx = [self._make_utterance("Hello?", is_owner=False)]
        should, msg = agent.should_intervene(context_override=ctx)
        assert should is True

    def test_case_insensitive_speak_prefix(self):
        agent = _make_agent(llm=_make_llm("speak: Great job today!"))
        ctx = [self._make_utterance("Just finished the report")]
        should, msg = agent.should_intervene(context_override=ctx)
        assert should is True
        assert "Great job" in msg


# ---------------------------------------------------------------------------
# Owner context line
# ---------------------------------------------------------------------------

class TestOwnerContextLine:
    def test_context_includes_minutes_ago(self):
        owner = _make_owner(secs_since_seen=120.0)
        agent = _make_agent(owner=owner)
        line = agent._owner_context_line
        assert "2 minute" in line

    def test_context_includes_hours_ago(self):
        owner = _make_owner(secs_since_seen=7200.0)
        agent = _make_agent(owner=owner)
        line = agent._owner_context_line
        assert "2 hour" in line

    def test_context_says_less_than_minute_when_recent(self):
        owner = _make_owner(secs_since_seen=20.0)
        agent = _make_agent(owner=owner)
        line = agent._owner_context_line
        assert "minute" in line or "less" in line

    def test_context_says_never_heard_when_none(self):
        owner = _make_owner(secs_since_seen=None)
        owner.seconds_since_owner_seen.return_value = None
        agent = _make_agent(owner=owner)
        line = agent._owner_context_line
        assert "not" in line.lower() or "never" in line.lower() or "startup" in line.lower()


# ---------------------------------------------------------------------------
# AgentManager.inject()
# ---------------------------------------------------------------------------

class TestAgentManagerInject:
    def test_inject_adds_new_slug(self):
        from core.agent_manager import AgentManager
        from unittest.mock import MagicMock
        orch = MagicMock()
        orch.get = MagicMock(return_value=MagicMock())
        registry = ToolRegistry()
        mgr = AgentManager(slugs=["qa"], orchestrator=orch, tool_registry=registry)
        fake_agent = MagicMock()
        mgr.inject("ally", fake_agent)
        assert "ally" in mgr.slugs

    def test_inject_replaces_existing(self):
        from core.agent_manager import AgentManager
        orch = MagicMock()
        registry = ToolRegistry()
        mgr = AgentManager(slugs=["qa"], orchestrator=orch, tool_registry=registry)
        fake1 = MagicMock()
        fake2 = MagicMock()
        mgr.inject("qa", fake1)
        mgr.inject("qa", fake2)
        mgr.set_agent("qa")
        assert mgr.get_current_agent() is fake2
