"""
Abstract base classes for all swappable hardware components.

Each ABC defines the contract a driver must fulfil. Concrete drivers live in
the same-named module (audio.py, display.py, …) and are selected at startup
by HardwareFactory based on the ``hardware:`` section of config.yaml.
"""
from abc import ABC, abstractmethod

import numpy as np


class AudioDevice(ABC):
    """Mic-in + speaker-out for a single audio hardware module."""

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Native capture sample rate in Hz (typically 16000)."""

    @property
    def sounddevice_input_device(self) -> str | None:
        """sounddevice device name/index for mic capture. None = system default."""
        return None

    @property
    def sounddevice_output_device(self) -> str | None:
        """sounddevice device name/index for speaker playback. None = system default."""
        return None

    @property
    def alsa_output_device(self) -> str | None:
        """ALSA device name passed to aplay for TTS output. None = system default."""
        return None

    @abstractmethod
    def get_chunk(self) -> np.ndarray:
        """
        Record one wake-word chunk and return a flat int16 array.
        Chunk size should be ~80ms (1280 samples at 16kHz) — optimal for
        OpenWakeWord. Blocks until the chunk is fully captured.
        """

    @abstractmethod
    def record_until_silence(self, vad) -> np.ndarray:
        """
        VAD-gated recording. Reads 30ms frames (480 samples at 16kHz) —
        the only frame sizes accepted by webrtcvad. Returns a flat int16
        array of all speech frames, or an empty array if nothing was captured.
        """

    @abstractmethod
    def play(self, audio: np.ndarray, samplerate: int = 22050) -> None:
        """Non-blocking playback of a raw audio array."""


class DisplayDevice(ABC):
    """Status display (OLED or similar)."""

    @abstractmethod
    def wake(self) -> None:
        """Turn the display on (or reset its sleep timer if already on)."""

    @abstractmethod
    def toggle(self) -> None:
        """Flip the display on/off programmatically."""

    @abstractmethod
    def set_server_url(self, url: str | None) -> None:
        """Set (or clear) the device server URL; starts/stops QR page cycling."""

    @abstractmethod
    def update(
        self,
        battery_pct: int,
        voltage: float,
        net_state: str,
        ssid: str,
        agent: str,
        interaction_mode: str = "",
        has_internet: bool = False,
        update_pending: bool = False,
        status_text: str = "Ready",
    ) -> None:
        """Refresh the stats page cache and re-render if the display is on."""

    @abstractmethod
    def update_mode(self, agent: str, interaction_mode: str | None = None) -> None:
        """Partial update: change the active agent and optional interaction mode."""


class PowerSource(ABC):
    """Battery / power-management module."""

    @abstractmethod
    def get_battery(self) -> tuple[int, float]:
        """
        Read battery state.
        Returns (percent: int 0–100, voltage: float in V).
        """


class LEDStrip(ABC):
    """RGB status LED strip."""

    @abstractmethod
    def set_color(self, color: str) -> None:
        """Set all LEDs to a named color: 'green', 'blue', 'red', or 'off'."""
