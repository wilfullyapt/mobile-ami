"""
Power / battery drivers.

X1202Power  reads the Geekworm X1202 UPS HAT via the MAX17043-compatible
            fuel-gauge IC at I2C address 0x36.
MockPower   returns a fixed dummy reading for dev/test environments.
"""
import smbus2

from hardware.abstract import PowerSource


class X1202Power(PowerSource):
    """
    Battery source for the Geekworm X1202 4-cell 18650 UPS HAT.

    The onboard MAX17043-compatible fuel gauge sits at I2C 0x36.
    Register map:
        0x02  VCELL  — 12-bit ADC, 1.25 mV per bit (upper 12 bits of word)
        0x04  SOC    — state of charge: upper byte = integer %, lower = 1/256 %
        0x0C  CONFIG — chip config (NOT state of charge — a common mis-mapping)
    """

    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self._addr = int(cfg.get("i2c_address", "0x36"), 16)
        self._bus = smbus2.SMBus(1)

    def get_battery(self) -> tuple[int, float]:
        """Returns (percent: 0–100, voltage: float in V)."""
        raw_soc = self._bus.read_word_data(self._addr, 0x04)
        soc = self._swap_bytes(raw_soc)
        percent = max(0, min(100, int(soc / 256)))

        raw_vcell = self._bus.read_word_data(self._addr, 0x02)
        vcell = self._swap_bytes(raw_vcell)
        voltage = round(vcell * 0.000078125, 2)   # 1.25 mV per bit, upper 12 bits

        return percent, voltage

    @staticmethod
    def _swap_bytes(word: int) -> int:
        """smbus2 read_word_data returns little-endian; swap to big-endian."""
        return ((word & 0xFF00) >> 8) | ((word & 0x00FF) << 8)


class MockPower(PowerSource):
    """Fixed-value power source for dev/test environments without real hardware."""

    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self._pct = cfg.get("mock_percent", 85)
        self._volt = cfg.get("mock_voltage", 4.1)

    def get_battery(self) -> tuple[int, float]:
        return self._pct, self._volt


# Module-level convenience shim retained for any code that still calls the old
# standalone get_battery() import.  New code should use PowerSource.get_battery().
def get_battery() -> tuple[int, float]:
    return X1202Power().get_battery()
