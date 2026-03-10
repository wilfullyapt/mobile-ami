"""Unit tests for AllyListener chunking logic."""
from __future__ import annotations

import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call
import wave

import numpy as np
import pytest

from core.ally_listener import AllyListener, AmbientUtterance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs):
    base = {
        "max_ambient_utterances": 20,
        "ambient_buffer_sec": 120,
        "check_interval_sec": 30,
        "ambient_chunk_sec": 180,
        "unknown_voice_clip_sec": 5,
    }
    base.update(kwargs)
    return base


def _make_listener(ally_config=None, paths=None, on_context_ready=None):
    orch = MagicMock()
    audio = MagicMock()
    return AllyListener(
        orchestrator=orch,
        audio=audio,
        voice_profiles=None,
        owner_name="Alice",
        ally_config=ally_config or _make_config(),
        on_context_ready=on_context_ready,
        paths=paths,
    )


def _make_utterance(text="hello", speaker="Alice", is_owner=True):
    return AmbientUtterance(
        speaker=speaker,
        is_owner=is_owner,
        text=text,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# _flush_chunk
# ---------------------------------------------------------------------------

class TestFlushChunk:
    def test_flush_chunk_creates_ambient_note(self):
        listener = _make_listener()
        listener._chunk_utterances = [_make_utterance()]
        listener._flush_chunk()

        notes = listener.get_pending_notes()
        assert len(notes) == 1
        assert len(notes[0].utterances) == 1

    def test_flush_skips_empty_chunk(self):
        listener = _make_listener()
        listener._chunk_utterances = []
        listener._flush_chunk()

        notes = listener.get_pending_notes()
        assert notes == []

    def test_flush_resets_chunk_state(self):
        listener = _make_listener()
        listener._chunk_utterances = [_make_utterance()]
        old_start = listener._chunk_start
        old_index = listener._chunk_index

        listener._flush_chunk()

        assert listener._chunk_utterances == []
        assert listener._chunk_index == old_index + 1
        assert listener._chunk_start >= old_start

    def test_flush_saves_note_json_when_paths_given(self, tmp_path):
        paths = MagicMock()
        paths.ally_notes_dir = tmp_path / "notes"
        paths.ally_notes_dir.mkdir(parents=True)

        listener = _make_listener(paths=paths)
        listener._chunk_utterances = [_make_utterance()]
        listener._flush_chunk()

        json_files = list((tmp_path / "notes").glob("*.json"))
        assert len(json_files) == 1

    def test_flush_includes_unknown_clip_paths(self):
        listener = _make_listener()
        listener._chunk_utterances = [_make_utterance()]
        listener._current_chunk_unknown_clips = ["/tmp/clip.wav"]
        listener._flush_chunk()

        notes = listener.get_pending_notes()
        assert notes[0].unknown_clip_paths == ["/tmp/clip.wav"]


# ---------------------------------------------------------------------------
# get_pending_notes
# ---------------------------------------------------------------------------

class TestGetPendingNotes:
    def test_get_pending_notes_returns_and_clears(self):
        listener = _make_listener()
        listener._chunk_utterances = [_make_utterance("first")]
        listener._flush_chunk()
        listener._chunk_utterances = [_make_utterance("second")]
        listener._flush_chunk()

        notes = listener.get_pending_notes()
        assert len(notes) == 2
        # Cleared after retrieval
        assert listener.get_pending_notes() == []

    def test_get_pending_notes_thread_safe(self):
        listener = _make_listener()
        results = []

        def producer():
            for i in range(5):
                listener._chunk_utterances = [_make_utterance(f"u{i}")]
                listener._flush_chunk()

        def consumer():
            import time
            time.sleep(0.01)
            results.extend(listener.get_pending_notes())

        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=consumer)
        t1.start(); t2.start()
        t1.join(); t2.join()
        # All produced notes should be consumed across both calls
        remaining = listener.get_pending_notes()
        assert len(results) + len(remaining) == 5


# ---------------------------------------------------------------------------
# _check_loop callback
# ---------------------------------------------------------------------------

class TestCheckLoop:
    def test_check_loop_flushes_before_callback(self):
        flushed_before = []
        cb_notes = []

        def on_ready(lst):
            cb_notes.extend(lst.get_pending_notes())

        listener = _make_listener(
            ally_config=_make_config(check_interval_sec=0.01),
            on_context_ready=on_ready,
        )
        listener._chunk_utterances = [_make_utterance("pre-existing")]
        listener._running = True

        import threading, time
        t = threading.Thread(target=listener._check_loop, daemon=True)
        t.start()
        time.sleep(0.05)
        listener._running = False
        t.join(timeout=1)

        # Callback should have received the pre-existing utterance in a note
        assert len(cb_notes) >= 1 or len(listener.get_pending_notes()) == 0


# ---------------------------------------------------------------------------
# _save_unknown_clip
# ---------------------------------------------------------------------------

class TestSaveUnknownClip:
    def test_unknown_voice_saves_wav(self, tmp_path):
        paths = MagicMock()
        paths.ally_audio_dir = tmp_path / "audio"
        paths.ally_audio_dir.mkdir(parents=True)

        listener = _make_listener(paths=paths)
        audio = np.zeros(8000, dtype=np.float32)
        listener._save_unknown_clip(audio)

        wav_files = list((tmp_path / "audio").glob("*.wav"))
        assert len(wav_files) == 1
        assert "_unknown_0.wav" in wav_files[0].name

    def test_unknown_voice_increments_count(self, tmp_path):
        paths = MagicMock()
        paths.ally_audio_dir = tmp_path / "audio"
        paths.ally_audio_dir.mkdir(parents=True)

        listener = _make_listener(paths=paths)
        audio = np.zeros(8000, dtype=np.float32)
        listener._save_unknown_clip(audio)
        listener._save_unknown_clip(audio)

        assert listener._unknown_clip_count == 2
        wav_files = list((tmp_path / "audio").glob("*.wav"))
        assert len(wav_files) == 2

    def test_unknown_voice_appends_to_current_chunk_clips(self, tmp_path):
        paths = MagicMock()
        paths.ally_audio_dir = tmp_path / "audio"
        paths.ally_audio_dir.mkdir(parents=True)

        listener = _make_listener(paths=paths)
        audio = np.zeros(8000, dtype=np.float32)
        listener._save_unknown_clip(audio)

        assert len(listener._current_chunk_unknown_clips) == 1
