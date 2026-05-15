"""
HardwareFactory — constructs concrete hardware drivers from the ``hardware:``
section of config.yaml.

Each create_*() method reads a ``driver`` key from its sub-section, looks it
up in a local driver registry, and returns a fully-initialised instance.
Adding a new driver requires only two steps:
  1. Write a class that extends the relevant ABC in hardware/abstract.py.
  2. Add an entry to the appropriate _*_DRIVERS dict below.

The factory also owns GPIO pin-factory configuration so the caller (main.py)
never needs to touch gpiozero internals directly.
"""
from __future__ import annotations

import logging

from hardware.abstract import AudioDevice, DisplayDevice, LEDStrip, PowerSource

logger = logging.getLogger(__name__)

# ── Driver registries ─────────────────────────────────────────────────────────
# Imports are deferred to avoid loading hardware libraries at module import time.

def _audio_drivers() -> dict[str, type[AudioDevice]]:
    from hardware.audio import DefaultAudio, SeeedReSpeakerAudio
    return {
        "default":         DefaultAudio,
        "seeed_respeaker": SeeedReSpeakerAudio,
    }

def _display_drivers() -> dict[str, type[DisplayDevice]]:
    from hardware.display import StatusDisplay, SSD1306Display
    return {
        "sh1106":  StatusDisplay,
        "ssd1306": SSD1306Display,
    }

def _led_drivers() -> dict[str, type[LEDStrip]]:
    from hardware.leds import APA102LEDs, NullLEDs
    return {
        "apa102": APA102LEDs,
        "none":   NullLEDs,
    }

def _power_drivers() -> dict[str, type[PowerSource]]:
    from hardware.power import X1202Power, MockPower
    return {
        "x1202": X1202Power,
        "mock":  MockPower,
    }


class HardwareFactory:
    """
    Creates hardware component instances from config.

    Usage::

        hw = HardwareFactory(config)
        hw.configure_gpio()          # must be called before create_buttons()
        audio   = hw.create_audio()
        display = hw.create_display()
        leds    = hw.create_leds()
        power   = hw.create_power()
    """

    def __init__(self, config: dict):
        self._hw = config.get("hardware", {})

    # ── GPIO setup ────────────────────────────────────────────────────────────

    def configure_gpio(self) -> None:
        """
        Set the gpiozero pin factory for the target platform.
        On Raspberry Pi 5 the default factories fail; LGPIOFactory(chip=0)
        is the correct choice.  Silently no-ops in dev/test environments.
        """
        factory_name = self._hw.get("buttons", {}).get("pin_factory", "lgpio")
        if factory_name == "lgpio":
            try:
                import gpiozero
                from gpiozero.pins.lgpio import LGPIOFactory
                gpiozero.Device.pin_factory = LGPIOFactory(chip=0)
                logger.info("GPIO pin factory set to LGPIOFactory(chip=0)")
            except Exception as exc:
                logger.debug("Could not set LGPIOFactory: %s (non-Pi env?)", exc)

    # ── Component factories ───────────────────────────────────────────────────

    def create_audio(self) -> AudioDevice:
        """Return the configured audio driver (default: DefaultAudio)."""
        from hardware.audio import DefaultAudio
        return self._build("audio", _audio_drivers(), DefaultAudio)

    def create_display(self) -> DisplayDevice:
        """Return the configured display driver (default: StatusDisplay / sh1106)."""
        from hardware.display import StatusDisplay
        return self._build("display", _display_drivers(), StatusDisplay)

    def create_leds(self) -> LEDStrip:
        """Return the configured LED driver (default: NullLEDs — safe everywhere)."""
        from hardware.leds import NullLEDs
        return self._build("leds", _led_drivers(), NullLEDs)

    def create_power(self) -> PowerSource:
        """Return the configured power driver (default: X1202Power)."""
        from hardware.power import X1202Power
        return self._build("power", _power_drivers(), X1202Power)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build(
        self,
        subsystem: str,
        registry: dict[str, type],
        default_cls: type,
    ):
        cfg = self._hw.get(subsystem, {})
        driver = cfg.get("driver")
        if driver is None:
            return default_cls(cfg)
        cls = registry.get(driver)
        if cls is None:
            raise ValueError(
                f"Unknown hardware.{subsystem} driver {driver!r}. "
                f"Available: {sorted(registry)}"
            )
        return cls(cfg)
