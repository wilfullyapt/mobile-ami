"""
Passive ambient listener for ally mode.

Runs as two background daemon threads:

    _listen_thread  — continuous audio capture loop:
                      get_chunk → VAD filter → record_until_silence
                      → speaker identify → STT → append to context buffer

    _check_thread   — fires a callback every check_interval_sec so the
                      main system can evaluate whether the ally should speak.

The context buffer is a bounded deque of AmbientUtterance objects. It is
thread-safe (protected by a lock) and automatically discards old entries
when max_ambient_utterances is reached.

AllyListener is started only when the device is in ALLY interaction mode.
It is stopped immediately when the mode is changed away from ALLY.
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from core.voice_profiles import VoiceProfileManager

logger = logging.getLogger(__name__)


@dataclass
class AmbientUtterance:
    """One captured speech segment from passive ambient listening."""
    speaker: Optional[str]        # identified name, or None if unrecognised
    is_owner: bool                 # True when speaker == owner_name
    text: str                      # transcribed content
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    audio_duration_sec: float = 0.0

    def seconds_ago(self) -> float:
        return (datetime.now(timezone.utc) - self.timestamp).total_seconds()

    def __repr__(self) -> str:
        who = self.speaker or "?"
        ago = int(self.seconds_ago())
        return f"<AmbientUtterance [{ago}s ago, {who}]: {self.text[:40]!r}>"


class AllyListener:
    """
    Passive ambient audio listener.

    Parameters
    ----------
    orchestrator:
        ModelOrchestrator used to fetch VAD, SPEAKER, and STT models.
    audio:
        AudioManager (provides get_chunk() and record_until_silence()).
    voice_profiles:
        Optional VoiceProfileManager for speaker identification. If None,
        all utterances will have speaker=None.
    owner_name:
        Display name of the device owner (from OwnerManager.owner_name).
        Used to set is_owner on each utterance.
    ally_config:
        The ``ally`` section of config.yaml.
    on_context_ready:
        Callback fired every check_interval_sec with this AllyListener as
        the argument. Use it to trigger AllyAgent.should_intervene().
    """

    def __init__(
        self,
        orchestrator,
        audio,
        voice_profiles: Optional["VoiceProfileManager"],
        owner_name: Optional[str],
        ally_config: dict,
        on_context_ready: Optional[Callable[["AllyListener"], None]] = None,
    ):
        self._orch = orchestrator
        self._audio = audio
        self._voice_profiles = voice_profiles
        self._owner_name = owner_name
        self._on_context_ready = on_context_ready

        self._max_utterances: int = ally_config.get("max_ambient_utterances", 20)
        self._buffer_sec: float = ally_config.get("ambient_buffer_sec", 120.0)
        self._check_interval: float = ally_config.get("check_interval_sec", 30.0)

        self._buffer: deque[AmbientUtterance] = deque(maxlen=self._max_utterances)
        self._lock = threading.Lock()
        self._running = False
        self._listen_thread: Optional[threading.Thread] = None
        self._check_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start both background threads."""
        if self._running:
            return
        self._running = True
        self._listen_thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="ally-listen"
        )
        self._listen_thread.start()
        if self._on_context_ready is not None:
            self._check_thread = threading.Thread(
                target=self._check_loop, daemon=True, name="ally-check"
            )
            self._check_thread.start()
        logger.info("AllyListener: started (check_interval=%.0fs)", self._check_interval)

    def stop(self) -> None:
        """Signal both threads to exit. They are daemon threads so no join needed."""
        self._running = False
        logger.info("AllyListener: stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Context queries (thread-safe)
    # ------------------------------------------------------------------

    def get_recent_context(self, max_age_sec: Optional[float] = None) -> list[AmbientUtterance]:
        """
        Return a snapshot of recent utterances, newest last.
        Filters by age if max_age_sec is given; otherwise uses ambient_buffer_sec.
        """
        cutoff = max_age_sec if max_age_sec is not None else self._buffer_sec
        with self._lock:
            return [u for u in self._buffer if u.seconds_ago() <= cutoff]

    def owner_present(self, within_sec: float = 60.0) -> bool:
        """True if the owner spoke within the last within_sec seconds."""
        with self._lock:
            return any(u.is_owner and u.seconds_ago() <= within_sec for u in self._buffer)

    def last_owner_utterance(self) -> Optional[AmbientUtterance]:
        """The most recent utterance from the owner, or None."""
        with self._lock:
            owner_utts = [u for u in self._buffer if u.is_owner]
            return owner_utts[-1] if owner_utts else None

    # ------------------------------------------------------------------
    # Background threads
    # ------------------------------------------------------------------

    def _listen_loop(self) -> None:
        from core.model_registry import ModelRole

        while self._running:
            try:
                # Quick VAD pre-check on a small chunk before committing to a
                # full record_until_silence() call, to avoid transcribing silence.
                chunk = self._audio.get_chunk()
                vad = self._orch.get(ModelRole.VAD)
                if not vad.is_speech(chunk):
                    time.sleep(0.05)
                    continue

                # Speech detected — capture the full utterance
                audio_frames = self._audio.record_until_silence(vad)
                if audio_frames is None or (
                    hasattr(audio_frames, "size") and audio_frames.size == 0
                ):
                    continue

                duration_sec = len(audio_frames) / 16_000.0

                # Speaker identification (optional)
                speaker: Optional[str] = None
                is_owner = False
                if self._voice_profiles is not None and self._orch.has(ModelRole.SPEAKER):
                    encoder = self._orch.get(ModelRole.SPEAKER)
                    profile, _ = self._voice_profiles.identify(audio_frames, encoder)
                    if profile:
                        speaker = profile.name
                        is_owner = (speaker == self._owner_name)

                # Transcription
                stt = self._orch.get(ModelRole.STT)
                text = stt.transcribe(audio_frames)
                if not text or not text.strip():
                    continue

                utterance = AmbientUtterance(
                    speaker=speaker,
                    is_owner=is_owner,
                    text=text.strip(),
                    audio_duration_sec=duration_sec,
                )
                with self._lock:
                    self._buffer.append(utterance)

                logger.debug(
                    "AllyListener captured [%s%s]: %s",
                    speaker or "?",
                    " (owner)" if is_owner else "",
                    text[:60],
                )

            except Exception as exc:
                if self._running:
                    logger.warning("AllyListener: listen loop error: %s", exc)
                time.sleep(1)

    def _check_loop(self) -> None:
        """Periodically call the context-ready callback."""
        while self._running:
            time.sleep(self._check_interval)
            if self._running and self._on_context_ready is not None:
                try:
                    self._on_context_ready(self)
                except Exception as exc:
                    logger.warning("AllyListener: context callback error: %s", exc)
