"""
conftest.py — session-level mocks for hardware/ML libraries unavailable
in the CI / development environment (no Raspberry Pi hardware required).

All these stubs are installed into sys.modules before any test module is
imported, so any code that does `import gpiozero` or `import smbus2` etc.
gets the mock instead of a ModuleNotFoundError.
"""
import sys
from unittest.mock import MagicMock


def _stub(name, **attrs):
    """Create a MagicMock module with optional named attributes."""
    mod = MagicMock(name=name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# ── GPIO / hardware ──────────────────────────────────────────────────────────
sys.modules.setdefault("gpiozero", _stub("gpiozero", Button=MagicMock))
sys.modules.setdefault("smbus2", _stub("smbus2", SMBus=MagicMock))
sys.modules.setdefault("sounddevice", _stub("sounddevice"))
sys.modules.setdefault("apa102", _stub("apa102", APA102=MagicMock))

# ── luma OLED ────────────────────────────────────────────────────────────────
sys.modules.setdefault("luma", _stub("luma"))
sys.modules.setdefault("luma.core", _stub("luma.core"))
sys.modules.setdefault("luma.core.interface", _stub("luma.core.interface"))
sys.modules.setdefault("luma.core.interface.serial", _stub("luma.core.interface.serial", i2c=MagicMock))
sys.modules.setdefault("luma.core.render", _stub("luma.core.render"))
sys.modules.setdefault("luma.oled", _stub("luma.oled"))
sys.modules.setdefault("luma.oled.device", _stub("luma.oled.device", ssd1306=MagicMock))

# ── ML / inference ───────────────────────────────────────────────────────────
sys.modules.setdefault("openwakeword", _stub("openwakeword"))
sys.modules.setdefault("openwakeword.model", _stub("openwakeword.model", Model=MagicMock))
sys.modules.setdefault("webrtcvad", _stub("webrtcvad", Vad=MagicMock))
sys.modules.setdefault("faster_whisper", _stub("faster_whisper", WhisperModel=MagicMock))
sys.modules.setdefault("ollama", _stub("ollama"))

# ── qrcode (may not be installed) ────────────────────────────────────────────
try:
    import qrcode  # noqa: F401
except ModuleNotFoundError:
    sys.modules.setdefault("qrcode", _stub("qrcode", QRCode=MagicMock))
