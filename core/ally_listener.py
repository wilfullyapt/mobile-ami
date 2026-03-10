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
import wave
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from core.voice_profiles import VoiceProfileManager
    from core.ami_paths import AmiPaths

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
        paths: Optional["AmiPaths"] = None,
    ):
        self._orch = orchestrator
        self._audio = audio
        self._voice_profiles = voice_profiles
        self._owner_name = owner_name
        self._on_context_ready = on_context_ready
        self._paths = paths

        self._max_utterances: int = ally_config.get("max_ambient_utterances", 20)
        self._buffer_sec: float = ally_config.get("ambient_buffer_sec", 120.0)
        self._check_interval: float = ally_config.get("check_interval_sec", 30.0)
        self._chunk_duration: float = ally_config.get("ambient_chunk_sec", 180.0)
        self._unknown_clip_sec: float = ally_config.get("unknown_voice_clip_sec", 5.0)

        self._buffer: deque[AmbientUtterance] = deque(maxlen=self._max_utterances)
        self._lock = threading.Lock()
        self._running = False
        self._listen_thread: Optional[threading.Thread] = None
        self._check_thread: Optional[threading.Thread] = None

        # Chunk state
        self._chunk_start: datetime = datetime.now(timezone.utc)
        self._chunk_utterances: list[AmbientUtterance] = []
        self._chunk_index: int = 0
        self._current_chunk_unknown_clips: list[str] = []
        self._unknown_clip_count: int = 0
        self._pending_notes: list = []  # list[AmbientNote]
        self._pending_lock = threading.Lock()

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

                # Chunk accumulation
                self._chunk_utterances.append(utterance)

                # Save unknown voice clip if speaker unrecognised and long enough
                if (
                    speaker is None
                    and duration_sec > 0.5
                    and self._paths is not None
                ):
                    clip = audio_frames[: int(self._unknown_clip_sec * 16_000)]
                    self._save_unknown_clip(clip)

                # Flush chunk if duration has elapsed
                elapsed = (datetime.now(timezone.utc) - self._chunk_start).total_seconds()
                if elapsed >= self._chunk_duration:
                    self._flush_chunk()

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
                # Flush any partial chunk before the callback so the caller
                # always receives up-to-date notes even in a quiet room.
                if self._chunk_utterances:
                    self._flush_chunk()
                try:
                    self._on_context_ready(self)
                except Exception as exc:
                    logger.warning("AllyListener: context callback error: %s", exc)

    # ------------------------------------------------------------------
    # Chunk management
    # ------------------------------------------------------------------

    def _flush_chunk(self) -> None:
        """Seal the current utterance chunk into an AmbientNote."""
        if not self._chunk_utterances:
            return

        from core.ambient_note import AmbientNote

        now = datetime.now(timezone.utc)
        note = AmbientNote(
            chunk_index=self._chunk_index,
            chunk_start=self._chunk_start,
            chunk_end=now,
            utterances=list(self._chunk_utterances),
            unknown_clip_paths=list(self._current_chunk_unknown_clips),
        )

        # Persist to disk if paths are configured
        if self._paths is not None:
            try:
                notes_dir = self._paths.ally_notes_dir
                notes_dir.mkdir(parents=True, exist_ok=True)
                fname = self._chunk_start.strftime("%Y%m%dT%H%M%S%f") + ".json"
                (notes_dir / fname).write_text(note.to_json())
            except Exception as exc:
                logger.warning("AllyListener: could not persist note: %s", exc)

        with self._pending_lock:
            self._pending_notes.append(note)

        logger.debug(
            "AllyListener: flushed chunk %d (%d utterances)",
            self._chunk_index,
            len(self._chunk_utterances),
        )

        # Reset chunk state
        self._chunk_utterances = []
        self._chunk_start = datetime.now(timezone.utc)
        self._chunk_index += 1
        self._current_chunk_unknown_clips = []

    def _save_unknown_clip(self, audio: np.ndarray) -> None:
        """Write a short WAV clip of an unrecognised speaker to disk."""
        try:
            audio_dir = self._paths.ally_audio_dir
            audio_dir.mkdir(parents=True, exist_ok=True)
            fname = (
                datetime.now().strftime("%Y%m%dT%H%M%S%f")
                + f"_unknown_{self._unknown_clip_count}.wav"
            )
            path = audio_dir / fname
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16_000)
                # Ensure int16 before writing
                if audio.dtype != np.int16:
                    pcm = (audio * 32768).clip(-32768, 32767).astype(np.int16)
                else:
                    pcm = audio
                wf.writeframes(pcm.tobytes())
            self._current_chunk_unknown_clips.append(str(path))
            self._unknown_clip_count += 1
            logger.debug("AllyListener: saved unknown clip → %s", path)
        except Exception as exc:
            logger.warning("AllyListener: could not save unknown clip: %s", exc)

    def get_pending_notes(self) -> list:
        """Return and clear all pending AmbientNotes (thread-safe)."""
        with self._pending_lock:
            notes, self._pending_notes = self._pending_notes, []
            return notes
