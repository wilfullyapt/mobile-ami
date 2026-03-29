import threading

import numpy as np
import sounddevice as sd


class AudioManager:
    """
    Thin wrapper around sounddevice for audio capture and playback.

    Recording methods are protected by an RLock so that AllyListener's
    continuous ambient capture and VoicePipeline's on-demand recording
    never open the input device simultaneously — which causes a sounddevice
    hardware conflict in ally mode.

    play() intentionally does NOT hold the lock because playback uses the
    output device (a separate hardware path from the input stream).
    """

    def __init__(self):
        self._record_lock = threading.RLock()

    def get_chunk(self) -> np.ndarray:
        """Record one 1024-sample chunk (64 ms at 16 kHz). Blocks until done."""
        with self._record_lock:
            chunk = sd.rec(1024, samplerate=16000, channels=1, dtype="int16")
            sd.wait()
            return chunk.flatten()

    def record_until_silence(self, vad) -> np.ndarray:
        """
        VAD-gated recording: accumulate frames until 10 consecutive silent
        frames are seen after at least one speech frame.

        Returns a flat int16 array, or an empty array if nothing was captured.
        """
        with self._record_lock:
            frames = []
            with sd.InputStream(samplerate=16000, channels=1, dtype="int16") as stream:
                while True:
                    data = stream.read(1024)[0]
                    if vad.is_speech(data):
                        frames.append(data)
                    elif len(frames) > 10:
                        break
        if not frames:
            return np.array([], dtype="int16")
        return np.concatenate(frames)

    def play(self, audio: np.ndarray) -> None:
        """Non-blocking TTS playback (output device — no lock needed)."""
        sd.play(audio, 22050)
