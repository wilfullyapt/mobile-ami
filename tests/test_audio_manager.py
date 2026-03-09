"""Unit tests for hardware/audio.py — focuses on thread-safety guarantees."""

import threading
import time
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

from hardware.audio import AudioManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vad(speech_sequence=None):
    """Return a VAD mock that returns True for speech_sequence items."""
    vad = MagicMock()
    if speech_sequence is None:
        # Default: speak for 12 frames then silence
        speech_sequence = [True] * 12 + [False]
    it = iter(speech_sequence)
    vad.is_speech.side_effect = lambda _data: next(it, False)
    return vad


# ---------------------------------------------------------------------------
# Basic interface
# ---------------------------------------------------------------------------

class TestGetChunk:
    def test_returns_flat_int16_array(self):
        with patch("hardware.audio.sd") as mock_sd:
            mock_sd.rec.return_value = np.zeros((1024, 1), dtype="int16")
            audio = AudioManager()
            chunk = audio.get_chunk()
        assert chunk.dtype == np.int16
        assert chunk.ndim == 1
        assert len(chunk) == 1024

    def test_calls_sd_rec_with_correct_params(self):
        with patch("hardware.audio.sd") as mock_sd:
            mock_sd.rec.return_value = np.zeros((1024, 1), dtype="int16")
            audio = AudioManager()
            audio.get_chunk()
        mock_sd.rec.assert_called_once_with(
            1024, samplerate=16000, channels=1, dtype="int16"
        )
        mock_sd.wait.assert_called_once()


class TestRecordUntilSilence:
    def test_returns_empty_array_when_only_zeros(self):
        """All-zero frames captured → returns a non-empty int16 array of zeros."""
        # 12 speech frames then silence → loop breaks after len(frames)==12
        speech_seq = [True] * 12 + [False]
        vad = MagicMock()
        it = iter(speech_seq)
        vad.is_speech.side_effect = lambda _d: next(it, False)

        zero_frame = np.zeros((1024, 1), dtype="int16")
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.read.side_effect = [(zero_frame, None)] * len(speech_seq)

        with patch("hardware.audio.sd") as mock_sd:
            mock_sd.InputStream.return_value = mock_stream
            audio = AudioManager()
            result = audio.record_until_silence(vad)

        assert isinstance(result, np.ndarray)
        assert result.dtype == np.int16
        assert len(result) == 12 * 1024

    def test_concatenates_speech_frames(self):
        frame = np.ones((1024,), dtype="int16")
        # 12 speech frames then 1 silent frame → loop breaks
        speech_calls = [True] * 12 + [False]
        vad = MagicMock()
        it = iter(speech_calls)
        vad.is_speech.side_effect = lambda _d: next(it, False)

        stream_data = [(frame.reshape(1024, 1), None)] * 13

        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.read.side_effect = stream_data

        with patch("hardware.audio.sd") as mock_sd:
            mock_sd.InputStream.return_value = mock_stream
            audio = AudioManager()
            result = audio.record_until_silence(vad)

        # 12 speech frames concatenated
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.int16
        assert len(result) == 12 * 1024


class TestPlay:
    def test_calls_sd_play(self):
        with patch("hardware.audio.sd") as mock_sd:
            audio = AudioManager()
            arr = np.zeros(1000, dtype="int16")
            audio.play(arr)
        mock_sd.play.assert_called_once()
        args = mock_sd.play.call_args[0]
        assert np.array_equal(args[0], arr)
        assert args[1] == 22050


# ---------------------------------------------------------------------------
# Thread-safety
# ---------------------------------------------------------------------------

class TestAudioManagerThreadSafety:
    def test_lock_prevents_simultaneous_get_chunk_calls(self):
        """Two threads calling get_chunk() should serialize, not overlap."""
        call_log = []
        lock = threading.Lock()

        def fake_rec(*args, **kwargs):
            with lock:
                call_log.append(("start", threading.current_thread().name))
            time.sleep(0.01)
            with lock:
                call_log.append(("end", threading.current_thread().name))
            return np.zeros((1024, 1), dtype="int16")

        with patch("hardware.audio.sd") as mock_sd:
            mock_sd.rec.side_effect = fake_rec
            mock_sd.wait.return_value = None
            audio = AudioManager()

            threads = [
                threading.Thread(target=audio.get_chunk, name=f"t{i}")
                for i in range(3)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # Verify starts and ends are interleaved correctly (no overlap)
        # Each "start" must be followed by its matching "end" before next "start"
        state = None
        for event, _ in call_log:
            if event == "start":
                assert state is None, "Two recordings started simultaneously"
                state = "recording"
            else:
                assert state == "recording"
                state = None

    def test_record_lock_is_reentrant(self):
        """RLock must not deadlock when same thread acquires it twice."""
        with patch("hardware.audio.sd"):
            audio = AudioManager()
            # Acquire once, then verify we can acquire again
            with audio._record_lock:
                acquired = audio._record_lock.acquire(blocking=False)
                assert acquired, "RLock should be reentrant for same thread"
                audio._record_lock.release()
