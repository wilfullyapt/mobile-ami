"""Unit tests for agents/base_ally_agent.py"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from agents.base_ally_agent import BaseAllyAgent, AllyContext
from agents.tools.tool_registry import ToolRegistry


# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing the ABC
# ---------------------------------------------------------------------------

class _ConcreteAlly(BaseAllyAgent):
    """Minimal concrete Ally for testing BaseAllyAgent infrastructure."""

    def __init__(self, *args, interaction_return="ok", analyzer_return=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._interaction_return = interaction_return
        self._analyzer_return = analyzer_return
        self.interaction_calls: list = []
        self.analyzer_calls: list = []

    def interaction_loop(self, text, speaker, ctx):
        self.interaction_calls.append((text, speaker, ctx))
        return self._interaction_return

    def analyzer_loop(self, notes, ctx):
        self.analyzer_calls.append((notes, ctx))
        return self._analyzer_return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_owner(name="Alice", has_owner=True, secs=30.0):
    owner = MagicMock()
    owner.has_owner = has_owner
    owner.owner_name = name if has_owner else None
    owner.seconds_since_owner_seen.return_value = secs
    owner.record_seen = MagicMock()
    return owner


def _make_soul(content="# Soul\nYou are Ami."):
    soul = MagicMock()
    soul.read.return_value = content
    return soul


def _make_spm(content="# Base\n{{SOUL}}\n"):
    spm = MagicMock()
    spm.read.return_value = content
    return spm


def _make_agent(
    owner=None,
    soul=None,
    spm=None,
    listener=None,
    interaction_return="ok",
    analyzer_return=None,
    ally_config=None,
):
    orch = MagicMock()
    orch.get.return_value = MagicMock()
    registry = ToolRegistry()
    return _ConcreteAlly(
        orchestrator=orch,
        tool_registry=registry,
        owner_manager=owner or _make_owner(),
        soul_manager=soul or _make_soul(),
        system_prompt_manager=spm or _make_spm(),
        ally_listener=listener,
        ally_config=ally_config or {},
        interaction_return=interaction_return,
        analyzer_return=analyzer_return,
    )


# ---------------------------------------------------------------------------
# supports_ally_mode
# ---------------------------------------------------------------------------

class TestSupportsAllyMode:
    def test_true_for_base_ally_subclass(self):
        assert _ConcreteAlly.supports_ally_mode() is True

    def test_false_for_plain_base_agent(self):
        from agents.base_agent import BaseAgent

        class Plain(BaseAgent):
            def process(self, text, speaker=None, context=None):
                return ""

        assert Plain.supports_ally_mode() is False


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def _ctx(self, soul="SOUL_TEXT", base="BASE {{SOUL}} END"):
        return AllyContext(
            soul_text=soul,
            system_base=base,
            owner_name="Alice",
            owner_context_line="Alice spoke recently.",
            is_owner_established=True,
        )

    def test_soul_injected_at_marker(self):
        agent = _make_agent()
        ctx = self._ctx()
        result = agent.build_system_prompt(ctx)
        assert "BASE SOUL_TEXT END" == result

    def test_no_marker_appends_soul(self):
        agent = _make_agent()
        ctx = self._ctx(base="BASE_ONLY")
        result = agent.build_system_prompt(ctx)
        assert "BASE_ONLY" in result
        assert "SOUL_TEXT" in result

    def test_empty_base_uses_soul_only(self):
        agent = _make_agent()
        ctx = self._ctx(base="")
        result = agent.build_system_prompt(ctx)
        assert result == "SOUL_TEXT"

    def test_extra_sections_appended(self):
        agent = _make_agent()
        ctx = self._ctx()
        result = agent.build_system_prompt(ctx, mode="MODE_SECTION")
        assert "MODE_SECTION" in result
        assert "---" in result

    def test_curly_braces_in_soul_dont_break(self):
        """soul.md may contain markdown with curly braces."""
        agent = _make_agent()
        ctx = self._ctx(soul="Soul with {braces} and {{doubles}}")
        result = agent.build_system_prompt(ctx)
        assert "{braces}" in result


# ---------------------------------------------------------------------------
# process() → delegates to interaction_loop + fires on_owner_spoken
# ---------------------------------------------------------------------------

class TestProcessWiring:
    def test_process_calls_interaction_loop(self):
        agent = _make_agent(interaction_return="hello")
        result = agent.process("hi")
        assert result == "hello"
        assert len(agent.interaction_calls) == 1

    def test_process_passes_text_and_speaker(self):
        agent = _make_agent()
        agent.process("hello world", speaker="Alice")
        text, speaker, ctx = agent.interaction_calls[0]
        assert text == "hello world"
        assert speaker == "Alice"

    def test_process_fires_on_owner_spoken_for_owner(self):
        spoken_utterances = []

        class TrackingAlly(_ConcreteAlly):
            def on_owner_spoken(self, utt, ctx):
                spoken_utterances.append(utt)

        orch = MagicMock()
        orch.get.return_value = MagicMock()
        registry = ToolRegistry()
        agent = TrackingAlly(
            orchestrator=orch,
            tool_registry=registry,
            owner_manager=_make_owner(name="Alice"),
            soul_manager=_make_soul(),
            system_prompt_manager=_make_spm(),
        )
        agent.process("hello", speaker="Alice")
        assert len(spoken_utterances) == 1
        assert spoken_utterances[0].speaker == "Alice"

    def test_process_does_not_fire_on_owner_spoken_for_stranger(self):
        spoken_utterances = []

        class TrackingAlly(_ConcreteAlly):
            def on_owner_spoken(self, utt, ctx):
                spoken_utterances.append(utt)

        orch = MagicMock()
        orch.get.return_value = MagicMock()
        registry = ToolRegistry()
        agent = TrackingAlly(
            orchestrator=orch,
            tool_registry=registry,
            owner_manager=_make_owner(name="Alice"),
            soul_manager=_make_soul(),
            system_prompt_manager=_make_spm(),
        )
        agent.process("hello", speaker="Bob")
        assert len(spoken_utterances) == 0

    def test_process_context_passed_to_interaction_loop(self):
        agent = _make_agent()
        mock_ctx = MagicMock()
        mock_ctx.history = []
        agent.process("hello", context=mock_ctx)
        _, _, ally_ctx = agent.interaction_calls[0]
        assert ally_ctx.agent_context is mock_ctx


# ---------------------------------------------------------------------------
# interval_listen() → delegates to analyzer_loop + fires hooks
# ---------------------------------------------------------------------------

class TestIntervalListenWiring:
    def test_interval_listen_calls_analyzer_loop(self):
        agent = _make_agent(analyzer_return=None)
        agent.interval_listen([])
        assert len(agent.analyzer_calls) == 1

    def test_interval_listen_returns_analyzer_result(self):
        agent = _make_agent(analyzer_return="hello there")
        result = agent.interval_listen([MagicMock(unknown_clip_paths=[])])
        assert result == "hello there"

    def test_on_ambient_context_short_circuits_analyzer(self):
        class EarlyAlly(_ConcreteAlly):
            def on_ambient_context(self, notes, ctx):
                return "early message"

        orch = MagicMock()
        orch.get.return_value = MagicMock()
        registry = ToolRegistry()
        agent = EarlyAlly(
            orchestrator=orch,
            tool_registry=registry,
            owner_manager=_make_owner(),
            soul_manager=_make_soul(),
            system_prompt_manager=_make_spm(),
        )
        result = agent.interval_listen([MagicMock(unknown_clip_paths=[])])
        assert result == "early message"
        assert len(agent.analyzer_calls) == 0

    def test_on_stranger_detected_called_for_unknown_clips(self):
        detected = []

        class DetectorAlly(_ConcreteAlly):
            def on_stranger_detected(self, clip_path, ctx):
                detected.append(clip_path)

        orch = MagicMock()
        orch.get.return_value = MagicMock()
        registry = ToolRegistry()
        agent = DetectorAlly(
            orchestrator=orch,
            tool_registry=registry,
            owner_manager=_make_owner(),
            soul_manager=_make_soul(),
            system_prompt_manager=_make_spm(),
        )
        note = MagicMock(unknown_clip_paths=["/tmp/clip1.wav", "/tmp/clip2.wav"])
        agent.interval_listen([note])
        assert detected == ["/tmp/clip1.wav", "/tmp/clip2.wav"]

    def test_on_owner_absent_fires_when_threshold_crossed(self):
        absent_calls = []

        class AbsentAlly(_ConcreteAlly):
            def on_owner_absent(self, seconds, ctx):
                absent_calls.append(seconds)
                return "Are you okay?"

        orch = MagicMock()
        orch.get.return_value = MagicMock()
        registry = ToolRegistry()
        owner = _make_owner(secs=400.0)
        agent = AbsentAlly(
            orchestrator=orch,
            tool_registry=registry,
            owner_manager=owner,
            soul_manager=_make_soul(),
            system_prompt_manager=_make_spm(),
            ally_config={"owner_absent_threshold_sec": 300},
        )
        result = agent.interval_listen([MagicMock(unknown_clip_paths=[])])
        assert "okay" in result.lower()
        assert len(absent_calls) == 1

    def test_on_owner_absent_not_fired_if_analyzer_spoke(self):
        absent_calls = []

        class AbsentAlly(_ConcreteAlly):
            def on_owner_absent(self, seconds, ctx):
                absent_calls.append(seconds)
                return "checking in"

        orch = MagicMock()
        orch.get.return_value = MagicMock()
        registry = ToolRegistry()
        owner = _make_owner(secs=400.0)
        agent = AbsentAlly(
            orchestrator=orch,
            tool_registry=registry,
            owner_manager=owner,
            soul_manager=_make_soul(),
            system_prompt_manager=_make_spm(),
            ally_config={"owner_absent_threshold_sec": 300},
            analyzer_return="already speaking",
        )
        result = agent.interval_listen([MagicMock(unknown_clip_paths=[])])
        assert result == "already speaking"
        assert len(absent_calls) == 0


# ---------------------------------------------------------------------------
# daily_update() → delegates to on_daily_reflect
# ---------------------------------------------------------------------------

class TestDailyUpdateWiring:
    def test_daily_update_calls_on_daily_reflect(self, tmp_path):
        reflect_calls = []

        class ReflectAlly(_ConcreteAlly):
            def on_daily_reflect(self, notes, summary, ctx):
                reflect_calls.append((notes, summary))

        from core.ami_paths import AmiPaths
        orch = MagicMock()
        orch.get.return_value = MagicMock()
        registry = ToolRegistry()
        paths = AmiPaths(root=str(tmp_path / "amini"))
        paths.ensure_dirs()
        agent = ReflectAlly(
            orchestrator=orch,
            tool_registry=registry,
            paths=paths,
            owner_manager=_make_owner(),
            soul_manager=_make_soul(),
            system_prompt_manager=_make_spm(),
        )
        agent.daily_update()
        assert len(reflect_calls) == 1
        notes, summary = reflect_calls[0]
        assert isinstance(notes, list)
        assert isinstance(summary, str)


# ---------------------------------------------------------------------------
# _build_ally_context
# ---------------------------------------------------------------------------

class TestBuildAllyContext:
    def test_soul_read_with_correct_has_owner_flag(self):
        soul = _make_soul()
        agent = _make_agent(soul=soul, owner=_make_owner(has_owner=True))
        agent.process("hello")
        soul.read.assert_called_with(has_owner=True)

    def test_soul_read_false_when_no_owner(self):
        soul = _make_soul()
        agent = _make_agent(soul=soul, owner=_make_owner(has_owner=False))
        agent.process("hello")
        soul.read.assert_called_with(has_owner=False)

    def test_ambient_utterances_from_listener(self):
        from core.ally.listener import AmbientUtterance
        utt = AmbientUtterance(
            speaker="Alice",
            is_owner=True,
            text="hello",
            timestamp=datetime.now(timezone.utc),
        )
        listener = MagicMock()
        listener.get_recent_context.return_value = [utt]

        agent = _make_agent(listener=listener)
        agent.process("hi")
        _, _, ctx = agent.interaction_calls[0]
        assert len(ctx.ambient_utterances) == 1
        assert ctx.ambient_utterances[0].text == "hello"

    def test_notes_included_in_analyzer_ctx(self):
        agent = _make_agent()
        note = MagicMock(unknown_clip_paths=[])
        agent.interval_listen([note])
        notes, ctx = agent.analyzer_calls[0]
        assert note in ctx.ambient_notes


# ---------------------------------------------------------------------------
# _owner_context_line
# ---------------------------------------------------------------------------

class TestOwnerContextLine:
    def test_minutes_ago(self):
        agent = _make_agent(owner=_make_owner(secs=120.0))
        assert "2 minute" in agent._owner_context_line

    def test_hours_ago(self):
        agent = _make_agent(owner=_make_owner(secs=7200.0))
        assert "2 hour" in agent._owner_context_line

    def test_less_than_minute(self):
        agent = _make_agent(owner=_make_owner(secs=20.0))
        line = agent._owner_context_line
        assert "minute" in line or "less" in line

    def test_never_seen(self):
        owner = _make_owner()
        owner.seconds_since_owner_seen.return_value = None
        agent = _make_agent(owner=owner)
        assert "not" in agent._owner_context_line.lower() or "startup" in agent._owner_context_line.lower()


# ---------------------------------------------------------------------------
# _format_utterances
# ---------------------------------------------------------------------------

class TestFormatUtterances:
    def _utt(self, text, speaker="Alice", is_owner=True, secs=30):
        from core.ally.listener import AmbientUtterance
        ts = datetime.now(timezone.utc) - timedelta(seconds=secs)
        return AmbientUtterance(speaker=speaker, is_owner=is_owner, text=text, timestamp=ts)

    def test_empty_list_returns_empty_string(self):
        agent = _make_agent()
        assert agent._format_utterances([]) == ""

    def test_formats_with_speaker_and_time(self):
        agent = _make_agent()
        result = agent._format_utterances([self._utt("hello")])
        assert "Alice" in result
        assert "hello" in result

    def test_owner_tag_added(self):
        agent = _make_agent()
        result = agent._format_utterances([self._utt("hello", is_owner=True)])
        assert "[owner]" in result

    def test_max_count_respected(self):
        agent = _make_agent()
        utts = [self._utt(f"msg{i}") for i in range(20)]
        lines = agent._format_utterances(utts, max_count=5).splitlines()
        assert len(lines) == 5
