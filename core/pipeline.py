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
    # Speaker identification — populated by _stage_identify_speaker() when
    # a SpeakerEncoder and VoiceProfileManager are wired into the pipeline.
    speaker: Optional[str] = None         # display name, e.g. "Mom"
    speaker_role: Optional[str] = None    # "parent" | "child" | "teen" | "guest"
    speaker_confidence: float = 0.0       # cosine similarity of best match


class VoicePipeline:
    """
    Coordinates the full voice interaction cycle as discrete stages:
        wake detection → listen (VAD-gated) → identify speaker
        → transcribe (STT) → respond (agent) → speak (TTS)

    Models are fetched from the orchestrator on each call so that
    hot-swaps take effect immediately.

    Speaker identification is optional: if ``voice_profiles`` is provided,
    a _stage_identify_speaker() step runs between listen and transcribe.
    The identified speaker name is passed to agent.process() so agents can
    personalise their responses.

    If conv_logger is provided, each completed interaction is persisted
    to ~/.amini/conversations/<agent>/ via ConversationLogger.log().
    """

    def __init__(
        self,
        orchestrator,
        agent_manager,
        audio,
        leds,
        on_speak: Callable[[str], None],
        conv_logger=None,
        voice_profiles=None,
    ):
        self._orch = orchestrator
        self._agents = agent_manager
        self._audio = audio
        self._leds = leds
        self._on_speak = on_speak
        self._conv_logger = conv_logger
        self._voice_profiles = voice_profiles  # Optional[VoiceProfileManager]

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
        self._stage_identify_speaker(ctx)
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

    def _stage_identify_speaker(self, ctx: PipelineContext):
        """
        Optionally identify the speaker from the recorded audio.

        Runs only when a VoiceProfileManager has been wired in and the
        orchestrator has a SPEAKER encoder loaded. Silently skips otherwise
        so the rest of the pipeline is unaffected on devices without this
        feature configured.
        """
        if self._voice_profiles is None:
            return
        if not self._orch.has(ModelRole.SPEAKER):
            return
        encoder = self._orch.get(ModelRole.SPEAKER)
        profile, confidence = self._voice_profiles.identify(ctx.audio, encoder)
        if profile:
            ctx.speaker = profile.name
            ctx.speaker_role = profile.role
            ctx.speaker_confidence = confidence
            logger.info("Speaker identified: %s (confidence=%.2f)", profile.name, confidence)

    def _stage_transcribe(self, ctx: PipelineContext):
        stt = self._orch.get(ModelRole.STT)
        text = stt.transcribe(ctx.audio)
        if text:
            ctx.transcript = text
            logger.info("Transcript: %s", text)

    def _stage_respond(self, ctx: PipelineContext):
        agent = self._agents.get_current_agent()
        ctx.agent_response = agent.process(ctx.transcript, speaker=ctx.speaker)
        if self._conv_logger and ctx.transcript and ctx.agent_response:
            self._conv_logger.log(
                self._agents.current, ctx.transcript, ctx.agent_response
            )

    def _stage_speak(self, ctx: PipelineContext):
        if ctx.agent_response:
            tts = self._orch.get(ModelRole.TTS)
            tts.speak(ctx.agent_response)
        self._leds.set_color("green")
