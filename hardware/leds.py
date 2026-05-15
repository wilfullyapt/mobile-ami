"""
LED strip drivers.

APA102LEDs  drives the 3 APA102 LEDs on the Keyestudio ReSpeaker 2-Mic Pi HAT
            via hardware SPI (MOSI=GPIO 10, CLK=GPIO 11) — the SPI0 default.
NullLEDs    silent no-op for environments without a fitted LED strip.
"""
import apa102

from hardware.abstract import LEDStrip


class APA102LEDs(LEDStrip):
    """
    APA102 LED strip driver for the ReSpeaker 2-Mic Pi HAT.

    The HAT has 3 APA102 LEDs wired to the Pi's hardware SPI0 bus
    (MOSI=GPIO 10, CLK=GPIO 11).  The apa102-pi library uses SPI0 by default,
    so no explicit pin arguments are needed.

    Config keys (all optional):
        num_leds          int   number of LEDs on the strip  (default 3)
        global_brightness int   APA102 global brightness 0–31 (default 31)
    """

    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        num_leds: int = cfg.get("num_leds", 3)
        brightness: int = cfg.get("global_brightness", 31)
        self._strip = apa102.APA102(num_led=num_leds, global_brightness=brightness)
        self._num_leds = num_leds

    def set_color(self, color: str) -> None:
        """Set all LEDs to a named color and push to hardware."""
        rgb = {
            "green": (0, 255, 0),
            "blue":  (0, 0, 255),
            "red":   (255, 0, 0),
            "off":   (0, 0, 0),
        }.get(color, (0, 0, 0))

        for i in range(self._num_leds):
            self._strip.set_pixel(i, *rgb)
        self._strip.show()


class NullLEDs(LEDStrip):
    """No-op LED driver for environments without a fitted LED strip."""

    def __init__(self, cfg: dict | None = None):
        pass

    def set_color(self, color: str) -> None:
        pass


# Backward-compatible alias — existing imports of LEDs keep working.
LEDs = APA102LEDs
