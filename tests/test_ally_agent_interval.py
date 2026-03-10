"""Unit tests for AllyAgent interval_listen, daily_update, and voice ID."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock
import threading

import numpy as np
import pytest

from agents.ally_agent import AllyAgent
from core.ally_listener import AmbientUtterance
from core.ambient_note import AmbientNote


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_utterance(text="hello", speaker="Alice", is_owner=True, seconds_ago=30):
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return AmbientUtterance(
        speaker=speaker,
        is_owner=is_owner,
        text=text,
        timestamp=ts,
    )


def _make_note(utterances=None, unknown_clips=None, index=0):
    now = datetime.now(timezone.utc)
    return AmbientNote(
        chunk_index=index,
        chunk_start=now - timedelta(seconds=180),
        chunk_end=now,
        utterances=utterances or [],
        unknown_clip_paths=unknown_clips or [],
    )


def _make_agent(llm_response="SILENT", with_paths=False, tmp_path=None, ally_config=None):
    orch = MagicMock()
    llm = MagicMock()
    llm.chat.return_value = llm_response
    llm.chat_with_tools.return_value = (llm_response, [])
    orch.get.return_value = llm
    orch.has.return_value = False

    soul = MagicMock()
    soul.read.return_value = "# Soul\nYou are Ami."

    owner = MagicMock()
    owner.owner_name = "Alice"
    owner.has_owner = True
    owner.is_owner_present.return_value = True
    owner.seconds_since_owner_seen.return_value = 10

    paths = None
    if with_paths and tmp_path is not None:
        from core.ami_paths import AmiPaths
        paths = AmiPaths(root=str(tmp_path / "amini"))
        paths.ensure_dirs()

    cfg = ally_config or {"replay_unknown_voices": True}

    agent = AllyAgent(
        orchestrator=orch,
        tool_registry=MagicMock(),
        paths=paths,
        soul_manager=soul,
        owner_manager=owner,
        on_owner_established=None,
        ally_listener=None,
        voice_profiles=None,
        ally_config=cfg,
    )
    agent._llm_mock = llm
    return agent


# ---------------------------------------------------------------------------
# supports_ally_mode
# ---------------------------------------------------------------------------

class TestSupportsAllyMode:
    def test_supports_ally_mode_true_for_ally_agent(self):
        assert AllyAgent.supports_ally_mode() is True

    def test_supports_ally_mode_false_for_base_subclass(self):
        from agents.base_agent import BaseAgent

        class MinimalAgent(BaseAgent):
            def process(self, text, speaker=None, context=None):
                return ""

        assert MinimalAgent.supports_ally_mode() is False


# ---------------------------------------------------------------------------
# interval_listen
# ---------------------------------------------------------------------------

class TestIntervalListen:
    def test_interval_listen_empty_notes_silent(self):
        agent = _make_agent()
        result = agent.interval_listen([])
        assert result is None
        agent._llm_mock.chat_with_tools.assert_not_called()

    def test_interval_listen_speak_response(self):
        agent = _make_agent(llm_response="SPEAK: Dinner is ready!")
        note = _make_note([_make_utterance("What's for dinner?")])
        result = agent.interval_listen([note])
        assert result == "Dinner is ready!"

    def test_interval_listen_silent(self):
        agent = _make_agent(llm_response="SILENT")
        note = _make_note([_make_utterance("Just some chat")])
        result = agent.interval_listen([note])
        assert result is None

    def test_interval_listen_tool_call_dispatched(self):
        """LLM returns a tool call for update_soul_section."""
        orch = MagicMock()
        llm = MagicMock()
        tool_call = {
            "function": {
                "name": "update_soul_section",
                "arguments": {"section": "Purpose", "content": "Help Alice stay organised."},
            }
        }
        # First call returns tool call, second returns SILENT
        llm.chat_with_tools.side_effect = [
            ("", [tool_call]),
            ("SILENT", []),
        ]
        orch.get.return_value = llm
        orch.has.return_value = False

        soul = MagicMock()
        soul.read.return_value = "# Soul"
        owner = MagicMock()
        owner.owner_name = "Alice"
        owner.has_owner = True
        owner.seconds_since_owner_seen.return_value = 5

        agent = AllyAgent(
            orchestrator=orch,
            tool_registry=MagicMock(),
            soul_manager=soul,
            owner_manager=owner,
            ally_config={"replay_unknown_voices": False},
        )

        note = _make_note([_make_utterance("test")])
        result = agent.interval_listen([note])
        soul.write_raw.assert_called_once()
        assert result is None  # SILENT after tool call

    def test_interval_listen_populates_pending_voice_id(self, tmp_path):
        # Write a real WAV file to load
        import wave as wavemod
        clip_path = tmp_path / "clip.wav"
        with wavemod.open(str(clip_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(np.zeros(8000, dtype=np.int16).tobytes())

        agent = _make_agent(llm_response="SILENT", ally_config={"replay_unknown_voices": True})
        note = _make_note(
            [_make_utterance("who goes there", speaker=None, is_owner=False)],
            unknown_clips=[str(clip_path)],
        )
        agent.interval_listen([note])
        assert len(agent._pending_voice_id) == 1


# ---------------------------------------------------------------------------
# daily_update
# ---------------------------------------------------------------------------

class TestDailyUpdate:
    def test_daily_update_runs_tool_loop(self, tmp_path):
        agent = _make_agent(llm_response="", with_paths=True, tmp_path=tmp_path)
        # Should not raise; LLM is called
        agent.daily_update()
        agent._llm_mock.chat_with_tools.assert_called()


# ---------------------------------------------------------------------------
# process — voice ID state machine
# ---------------------------------------------------------------------------

class TestProcessVoiceId:
    def test_process_presents_clip_when_pending(self, tmp_path):
        import wave as wavemod
        clip_path = tmp_path / "clip.wav"
        with wavemod.open(str(clip_path), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
            wf.writeframes(np.zeros(8000, dtype=np.int16).tobytes())

        agent = _make_agent(ally_config={"replay_unknown_voices": True})
        agent._owner._owner = MagicMock()
        audio = np.zeros(8000, dtype=np.float32)
        agent._pending_voice_id = [(str(clip_path), audio)]

        with patch.object(agent, "_play_audio_clip") as mock_play:
            response = agent.process("Hi Ami", speaker="Alice")

        mock_play.assert_called_once()
        assert "don't recognise" in response or "Who is this" in response
        assert agent._awaiting_voice_name is True

    def test_process_awaiting_name_enrolls_profile(self):
        agent = _make_agent(ally_config={"replay_unknown_voices": True})
        agent._voice_profiles = MagicMock()
        agent._orchestrator.has.return_value = True
        encoder = MagicMock()
        agent._orchestrator.get.return_value = encoder

        audio = np.zeros(8000, dtype=np.float32)
        agent._awaiting_voice_name = True
        agent._pending_voice_id = [("/tmp/clip.wav", audio)]

        response = agent.process("It's Bob", speaker="Alice")
        agent._voice_profiles.enroll.assert_called_once_with("Bob", audio, encoder, role="guest")
        assert agent._awaiting_voice_name is False
        assert "Bob" in response

    def test_on_exit_resets_awaiting_voice_name(self):
        agent = _make_agent()
        agent._awaiting_voice_name = True
        agent.on_exit()
        assert agent._awaiting_voice_name is False


# ---------------------------------------------------------------------------
# should_intervene backward compat
# ---------------------------------------------------------------------------

class TestShouldInterveneBackwardCompat:
    def test_should_intervene_backward_compat(self):
        agent = _make_agent(llm_response="SILENT")
        # should_intervene should still work as before
        speak, msg = agent.should_intervene(context_override=[])
        assert speak is False
        assert msg is None

    def test_should_intervene_speak(self):
        agent = _make_agent(llm_response="SPEAK: Hello there!")
        speak, msg = agent.should_intervene(context_override=[_make_utterance()])
        assert speak is True
        assert msg == "Hello there!"
