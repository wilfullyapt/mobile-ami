"""Unit tests for core/pipeline.py"""

import pytest
import numpy as np
from unittest.mock import MagicMock, call, patch

from core.pipeline import PipelineContext, VoicePipeline
from core.model_registry import ModelRole


def _make_orchestrator(stt_text="hello world"):
    """Build a minimal mock orchestrator whose models return useful values."""
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = stt_text

    mock_tts = MagicMock()
    mock_vad = MagicMock()
    mock_wake = MagicMock()

    orch = MagicMock()
    orch.get.side_effect = lambda role: {
        ModelRole.STT: mock_stt,
        ModelRole.TTS: mock_tts,
        ModelRole.VAD: mock_vad,
        ModelRole.WAKE: mock_wake,
    }[role]

    return orch, mock_stt, mock_tts, mock_vad, mock_wake


def _make_audio(frames=None):
    """Mock AudioManager that returns audio data."""
    audio = MagicMock()
    data = frames if frames is not None else np.zeros(16000, dtype=np.float32)
    audio.record_until_silence.return_value = data
    return audio


def _make_agent_manager(response="test response"):
    agents = MagicMock()
    agent = MagicMock()
    agent.process.return_value = response
    agents.get_current_agent.return_value = agent
    return agents, agent


class TestPipelineContext:
    def test_default_values(self):
        ctx = PipelineContext()
        assert ctx.audio is None
        assert ctx.transcript is None
        assert ctx.agent_response is None
        assert ctx.should_abort is False

    def test_can_set_fields(self):
        audio = np.zeros(100)
        ctx = PipelineContext(audio=audio, transcript="hi", agent_response="hello")
        assert ctx.transcript == "hi"
        assert ctx.agent_response == "hello"


class TestVoicePipelineRunOnce:
    def _make_pipeline(self, stt_text="hello", agent_response="world", audio_frames=None):
        orch, stt, tts, vad, wake = _make_orchestrator(stt_text)
        audio = _make_audio(audio_frames)
        agents, agent = _make_agent_manager(agent_response)
        on_speak = MagicMock()
        leds = MagicMock()
        pipeline = VoicePipeline(
            orchestrator=orch,
            agent_manager=agents,
            audio=audio,
            leds=leds,
            on_speak=on_speak,
        )
        return pipeline, orch, stt, tts, vad, audio, agents, agent, on_speak, leds

    def test_full_happy_path(self):
        pipeline, orch, stt, tts, vad, audio, agents, agent, on_speak, leds = self._make_pipeline()
        ctx = pipeline.run_once()

        assert ctx.should_abort is False
        assert ctx.transcript == "hello"
        assert ctx.agent_response == "world"
        stt.transcribe.assert_called_once()
        agent.process.assert_called_once_with("hello")
        tts.speak.assert_called_once_with("world")

    def test_leds_set_blue_on_listen(self):
        pipeline, *rest = self._make_pipeline()
        leds = rest[-1]
        pipeline.run_once()
        leds.set_color.assert_any_call("blue")

    def test_leds_set_green_after_speak(self):
        pipeline, *rest = self._make_pipeline()
        leds = rest[-1]
        pipeline.run_once()
        leds.set_color.assert_called_with("green")

    def test_aborts_when_audio_is_none(self):
        pipeline, orch, stt, tts, vad, audio, agents, agent, on_speak, leds = self._make_pipeline()
        audio.record_until_silence.return_value = None
        ctx = pipeline.run_once()

        assert ctx.should_abort is True
        stt.transcribe.assert_not_called()
        agent.process.assert_not_called()

    def test_aborts_when_audio_is_empty(self):
        pipeline, orch, stt, tts, vad, audio, agents, agent, on_speak, leds = self._make_pipeline(
            audio_frames=np.zeros(0, dtype=np.float32)
        )
        ctx = pipeline.run_once()

        assert ctx.should_abort is True
        stt.transcribe.assert_not_called()

    def test_skips_respond_and_speak_when_transcript_empty(self):
        pipeline, orch, stt, tts, vad, audio, agents, agent, on_speak, leds = self._make_pipeline(
            stt_text=""
        )
        ctx = pipeline.run_once()

        assert ctx.transcript is None
        agent.process.assert_not_called()
        tts.speak.assert_not_called()

    def test_no_speak_when_agent_returns_empty(self):
        pipeline, orch, stt, tts, vad, audio, agents, agent, on_speak, leds = self._make_pipeline(
            agent_response=""
        )
        ctx = pipeline.run_once()
        tts.speak.assert_not_called()

    def test_listen_stage_announces_listening(self):
        pipeline, orch, stt, tts, vad, audio, agents, agent, on_speak, leds = self._make_pipeline()
        pipeline.run_once()
        on_speak.assert_any_call("Listening")

    def test_vad_passed_to_record_until_silence(self):
        pipeline, orch, stt, tts, vad, audio, agents, agent, on_speak, leds = self._make_pipeline()
        pipeline.run_once()
        audio.record_until_silence.assert_called_once_with(vad)

    def test_audio_passed_to_stt(self):
        audio_data = np.ones(8000, dtype=np.float32)
        pipeline, orch, stt, tts, vad, audio, agents, agent, on_speak, leds = self._make_pipeline(
            audio_frames=audio_data
        )
        pipeline.run_once()
        stt.transcribe.assert_called_once_with(audio_data)


class TestVoicePipelineWakeLoop:
    def test_wake_loop_calls_run_once_on_detection(self):
        orch, stt, tts, vad, wake = _make_orchestrator()
        # Wake word detected on first chunk only
        wake.detect.side_effect = [True, False, False]

        audio = _make_audio()
        agents, agent = _make_agent_manager()
        leds = MagicMock()
        on_speak = MagicMock()

        pipeline = VoicePipeline(
            orchestrator=orch,
            agent_manager=agents,
            audio=audio,
            leds=leds,
            on_speak=on_speak,
        )

        call_count = 0

        def stop_after_three():
            nonlocal call_count
            call_count += 1
            return call_count >= 3

        chunks = [np.zeros(512) for _ in range(3)]
        chunk_iter = iter(chunks)

        with patch.object(pipeline, "run_once") as mock_run_once, \
             patch("time.sleep"):
            pipeline.wake_loop(lambda: next(chunk_iter), stop_flag=stop_after_three)
            assert mock_run_once.call_count == 1

    def test_wake_loop_stops_on_flag(self):
        orch, stt, tts, vad, wake = _make_orchestrator()
        wake.detect.return_value = False

        pipeline = VoicePipeline(
            orchestrator=orch,
            agent_manager=MagicMock(),
            audio=MagicMock(),
            leds=MagicMock(),
            on_speak=MagicMock(),
        )

        call_count = 0

        def stop_immediately():
            return True

        with patch("time.sleep"):
            pipeline.wake_loop(lambda: np.zeros(512), stop_flag=stop_immediately)
        # Should exit without calling run_once
