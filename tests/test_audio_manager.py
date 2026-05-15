"""Unit tests for hardware/audio.py — interface contract and thread-safety."""

import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from hardware.audio import AudioManager, DefaultAudio, SeeedReSpeakerAudio


# ---------------------------------------------------------------------------
# Chunk-size constants (must stay in sync with DefaultAudio class)
# ---------------------------------------------------------------------------

_WAKE_CHUNK = DefaultAudio._WAKE_CHUNK   # 1280 samples = 80ms at 16kHz
_VAD_CHUNK  = DefaultAudio._VAD_CHUNK    # 480  samples = 30ms at 16kHz


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_audio(cfg=None):
    return DefaultAudio(cfg)

def _make_vad(speech_sequence=None):
    vad = MagicMock()
    if speech_sequence is None:
        speech_sequence = [True] * 12 + [False]
    it = iter(speech_sequence)
    vad.is_speech.side_effect = lambda _data: next(it, False)
    return vad


# ---------------------------------------------------------------------------
# get_chunk — wake-word capture
# ---------------------------------------------------------------------------

class TestGetChunk:
    def test_returns_flat_int16_array(self):
        with patch("hardware.audio.sd") as mock_sd:
            mock_sd.rec.return_value = np.zeros((_WAKE_CHUNK, 1), dtype="int16")
            audio = _make_audio()
            chunk = audio.get_chunk()
        assert chunk.dtype == np.int16
        assert chunk.ndim == 1
        assert len(chunk) == _WAKE_CHUNK

    def test_calls_sd_rec_with_correct_params(self):
        with patch("hardware.audio.sd") as mock_sd:
            mock_sd.rec.return_value = np.zeros((_WAKE_CHUNK, 1), dtype="int16")
            audio = _make_audio()
            audio.get_chunk()
        mock_sd.rec.assert_called_once_with(
            _WAKE_CHUNK,
            samplerate=16000,
            channels=1,
            dtype="int16",
            device=None,            # default driver has no explicit device
        )
        mock_sd.wait.assert_called_once()

    def test_seeed_driver_passes_device_name(self):
        with patch("hardware.audio.sd") as mock_sd:
            mock_sd.rec.return_value = np.zeros((_WAKE_CHUNK, 1), dtype="int16")
            audio = SeeedReSpeakerAudio()
            audio.get_chunk()
        _, kwargs = mock_sd.rec.call_args
        assert kwargs["device"] == SeeedReSpeakerAudio._DEFAULT_DEVICE


# ---------------------------------------------------------------------------
# record_until_silence — VAD-gated capture
# ---------------------------------------------------------------------------

class TestRecordUntilSilence:
    def _make_stream(self, speech_sequence):
        """Return a mock InputStream that yields VAD_CHUNK-sized frames."""
        zero_frame = np.zeros((_VAD_CHUNK, 1), dtype="int16")
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=False)
        mock_stream.read.side_effect = [(zero_frame, None)] * len(speech_sequence)
        return mock_stream

    def test_returns_concatenated_speech_frames(self):
        speech_seq = [True] * 12 + [False]
        vad = _make_vad(speech_seq)
        mock_stream = self._make_stream(speech_seq)

        with patch("hardware.audio.sd") as mock_sd:
            mock_sd.InputStream.return_value = mock_stream
            audio = _make_audio()
            result = audio.record_until_silence(vad)

        assert isinstance(result, np.ndarray)
        assert result.dtype == np.int16
        assert len(result) == 12 * _VAD_CHUNK

    def test_stream_reads_vad_chunk_size_frames(self):
        speech_seq = [True] * 12 + [False]
        vad = _make_vad(speech_seq)
        mock_stream = self._make_stream(speech_seq)

        with patch("hardware.audio.sd") as mock_sd:
            mock_sd.InputStream.return_value = mock_stream
            _make_audio().record_until_silence(vad)

        for call in mock_stream.read.call_args_list:
            assert call[0][0] == _VAD_CHUNK


# ---------------------------------------------------------------------------
# play — non-blocking output
# ---------------------------------------------------------------------------

class TestPlay:
    def test_calls_sd_play_with_array_and_samplerate(self):
        with patch("hardware.audio.sd") as mock_sd:
            audio = _make_audio()
            arr = np.zeros(1000, dtype="int16")
            audio.play(arr)
        args = mock_sd.play.call_args[0]
        assert np.array_equal(args[0], arr)
        assert args[1] == 22050   # Piper TTS output rate


# ---------------------------------------------------------------------------
# Driver properties
# ---------------------------------------------------------------------------

class TestDriverProperties:
    def test_default_audio_has_no_device(self):
        audio = _make_audio()
        assert audio.sounddevice_input_device is None
        assert audio.sounddevice_output_device is None
        assert audio.alsa_output_device is None

    def test_seeed_driver_sets_device_name(self):
        audio = SeeedReSpeakerAudio()
        assert audio.sounddevice_input_device == SeeedReSpeakerAudio._DEFAULT_DEVICE
        assert audio.sounddevice_output_device == SeeedReSpeakerAudio._DEFAULT_DEVICE

    def test_custom_device_via_cfg(self):
        audio = DefaultAudio({"input_device": "custom-card", "alsa_output_device": "hw:0,0"})
        assert audio.sounddevice_input_device == "custom-card"
        assert audio.alsa_output_device == "hw:0,0"

    def test_audio_manager_alias(self):
        assert AudioManager is DefaultAudio


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
            return np.zeros((_WAKE_CHUNK, 1), dtype="int16")

        with patch("hardware.audio.sd") as mock_sd:
            mock_sd.rec.side_effect = fake_rec
            mock_sd.wait.return_value = None
            audio = _make_audio()

            threads = [
                threading.Thread(target=audio.get_chunk, name=f"t{i}")
                for i in range(3)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        state = None
        for event, _ in call_log:
            if event == "start":
                assert state is None, "Two recordings started simultaneously"
                state = "recording"
            else:
                assert state == "recording"
                state = None

    def test_record_lock_is_reentrant(self):
        with patch("hardware.audio.sd"):
            audio = _make_audio()
            with audio._record_lock:
                acquired = audio._record_lock.acquire(blocking=False)
                assert acquired, "RLock should be reentrant for same thread"
                audio._record_lock.release()
