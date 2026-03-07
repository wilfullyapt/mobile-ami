import time
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from core.model_registry import ModelRole

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Carries state through each stage of a single listen→respond cycle."""
    audio: Optional[np.ndarray] = None
    transcript: Optional[str] = None
    agent_response: Optional[str] = None
    should_abort: bool = False


class VoicePipeline:
    """
    Coordinates the full voice interaction cycle as discrete stages:
        wake detection → listen (VAD-gated) → transcribe (STT)
        → respond (agent) → speak (TTS)

    Models are fetched from the orchestrator on each call so that
    hot-swaps take effect immediately.
    """

    def __init__(self, orchestrator, agent_manager, audio, leds, on_speak: Callable[[str], None]):
        self._orch = orchestrator
        self._agents = agent_manager
        self._audio = audio
        self._leds = leds
        self._on_speak = on_speak

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_once(self) -> PipelineContext:
        """
        Execute one full listen→respond cycle.
        Returns the context so callers can inspect results.
        """
        ctx = PipelineContext()
        self._stage_listen(ctx)
        if ctx.should_abort:
            return ctx
        self._stage_transcribe(ctx)
        if not ctx.transcript:
            return ctx
        self._stage_respond(ctx)
        self._stage_speak(ctx)
        return ctx

    def wake_loop(self, audio_chunk_fn: Callable[[], np.ndarray], stop_flag: Callable[[], bool] = lambda: False):
        """
        Blocking loop: continuously read audio chunks, detect wake word,
        then hand off to run_once(). Returns when stop_flag() is True.
        """
        while not stop_flag():
            chunk = audio_chunk_fn()
            wake = self._orch.get(ModelRole.WAKE)
            if wake.detect(chunk):
                logger.info("Wake word detected")
                self.run_once()
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    def _stage_listen(self, ctx: PipelineContext):
        self._leds.set_color("blue")
        self._on_speak("Listening")
        vad = self._orch.get(ModelRole.VAD)
        audio = self._audio.record_until_silence(vad)
        if audio is None or (hasattr(audio, "size") and audio.size == 0):
            ctx.should_abort = True
            self._leds.set_color("green")
            return
        ctx.audio = audio

    def _stage_transcribe(self, ctx: PipelineContext):
        stt = self._orch.get(ModelRole.STT)
        text = stt.transcribe(ctx.audio)
        if text:
            ctx.transcript = text
            logger.info("Transcript: %s", text)

    def _stage_respond(self, ctx: PipelineContext):
        agent = self._agents.get_current_agent()
        ctx.agent_response = agent.process(ctx.transcript)

    def _stage_speak(self, ctx: PipelineContext):
        if ctx.agent_response:
            tts = self._orch.get(ModelRole.TTS)
            tts.speak(ctx.agent_response)
        self._leds.set_color("green")
