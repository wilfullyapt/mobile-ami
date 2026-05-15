"""
Audio drivers — mic capture and speaker playback.

DefaultAudio    uses the system's default ALSA device.
SeeedReSpeakerAudio  targets the Keyestudio ReSpeaker 2-Mic Pi HAT (WM8960 via
                     seeed-voicecard) with explicit device selection.

Both drivers use:
  - 1280-sample (80ms) chunks for wake-word detection  — optimal for OpenWakeWord
  -  480-sample (30ms) chunks for VAD-gated recording  — required by webrtcvad
    (webrtcvad raises ValueError for any other frame length at 16kHz)
"""
import threading

import numpy as np
import sounddevice as sd

from hardware.abstract import AudioDevice


class DefaultAudio(AudioDevice):
    """
    AudioDevice backed by sounddevice, targeting the system default ALSA device.
    Recording methods are protected by an RLock so that AllyListener's
    continuous ambient capture and VoicePipeline's on-demand recording never
    open the input stream simultaneously.
    """

    _SAMPLE_RATE = 16000
    _WAKE_CHUNK = 1280   # 80ms — optimal for OpenWakeWord
    _VAD_CHUNK = 480     # 30ms — one of the only valid webrtcvad frame sizes

    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self._record_lock = threading.RLock()
        self._in_dev: str | None = cfg.get("input_device")
        self._out_dev: str | None = cfg.get("output_device")
        self._alsa_out: str | None = cfg.get("alsa_output_device")

    # ── AudioDevice properties ────────────────────────────────────────────────

    @property
    def sample_rate(self) -> int:
        return self._SAMPLE_RATE

    @property
    def sounddevice_input_device(self) -> str | None:
        return self._in_dev

    @property
    def sounddevice_output_device(self) -> str | None:
        return self._out_dev

    @property
    def alsa_output_device(self) -> str | None:
        return self._alsa_out

    # ── AudioDevice interface ─────────────────────────────────────────────────

    def get_chunk(self) -> np.ndarray:
        """Record one 80ms wake-word chunk. Blocks until done."""
        with self._record_lock:
            chunk = sd.rec(
                self._WAKE_CHUNK,
                samplerate=self._SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=self._in_dev,
            )
            sd.wait()
            return chunk.flatten()

    def record_until_silence(self, vad) -> np.ndarray:
        """
        VAD-gated recording using 30ms frames (480 samples at 16kHz).
        Accumulates frames until 1 silent frame is seen after at least 10
        speech frames, then returns the concatenated speech audio.
        """
        with self._record_lock:
            frames = []
            with sd.InputStream(
                samplerate=self._SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=self._in_dev,
            ) as stream:
                while True:
                    data = stream.read(self._VAD_CHUNK)[0]
                    if vad.is_speech(data):
                        frames.append(data)
                    elif len(frames) > 10:
                        break
        if not frames:
            return np.array([], dtype="int16")
        return np.concatenate(frames)

    def play(self, audio: np.ndarray, samplerate: int = 22050) -> None:
        """Non-blocking playback on the output device. No lock — separate hardware path."""
        sd.play(audio, samplerate, device=self._out_dev)


class SeeedReSpeakerAudio(DefaultAudio):
    """
    AudioDevice for the Keyestudio ReSpeaker 2-Mic Pi HAT V1 (WM8960 codec).

    Requires the seeed-voicecard ALSA driver:
        git clone https://github.com/HinTak/seeed-voicecard /tmp/seeed-voicecard
        cd /tmp/seeed-voicecard && sudo ./install.sh

    Hardware connections (manual breadboard wiring):
        Power/GND  → Pi 3.3V / 5V / GND pins
        I2C SDA/SCL → GPIO 2 / 3  (shared with OLED + X1202)
        I2S BCLK   → GPIO 18 (PCM_CLK)
        I2S LRCLK  → GPIO 19 (PCM_FS)
        I2S DIN    → GPIO 20 (PCM_DIN)
        I2S DOUT   → GPIO 21 (PCM_DOUT)
        APA102 LEDs → SPI0  MOSI=GPIO 10 / CLK=GPIO 11  (handled by leds.py)
    """

    _DEFAULT_DEVICE = "seeed-2mic-voicecard"

    def __init__(self, cfg: dict | None = None):
        cfg = dict(cfg or {})
        cfg.setdefault("input_device", self._DEFAULT_DEVICE)
        cfg.setdefault("output_device", self._DEFAULT_DEVICE)
        super().__init__(cfg)


# Backward-compatible alias — existing imports of AudioManager keep working.
AudioManager = DefaultAudio
