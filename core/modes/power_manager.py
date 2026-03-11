"""
PowerManager — CPU frequency governor control for battery optimisation.

Maps each interaction mode to the most appropriate Linux cpufreq governor:

    MANUAL    → powersave    Minimal drain; device is button-only,
                             no continuous inference.
    HOT_WORD  → ondemand     Moderate; wake word detection + burst
                             inference on activation.
    ALLY      → performance  Full; continuous ambient recording,
                             speaker ID, STT, and LLM in ally mode.

Uses the Linux sysfs cpufreq interface:
    /sys/devices/system/cpu/cpuN/cpufreq/scaling_governor

Silently no-ops on non-Linux platforms, in containers without the sysfs
interface, and when the process lacks write permission (e.g. during
development and tests). This ensures the rest of the system is never
affected by power-management failures.

Raspberry Pi note
-----------------
The RPi OS ships the ``ondemand`` governor by default. Ensure the
``cpufreq-utils`` package is installed if you want ``powersave``:
    sudo apt install cpufreq-utils
"""

import logging
from pathlib import Path
from typing import Optional

from core.modes.interaction_mode import InteractionMode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Governor mapping
# ---------------------------------------------------------------------------

_GOVERNOR_MAP: dict[InteractionMode, str] = {
    InteractionMode.MANUAL:   "powersave",
    InteractionMode.HOT_WORD: "ondemand",
    InteractionMode.ALLY:     "performance",
}

_CPUFREQ_BASE = Path("/sys/devices/system/cpu")


def _governor_paths() -> list[Path]:
    """Return all cpufreq governor sysfs paths, sorted by CPU index."""
    return sorted(_CPUFREQ_BASE.glob("cpu[0-9]*/cpufreq/scaling_governor"))


# ---------------------------------------------------------------------------
# PowerManager
# ---------------------------------------------------------------------------

class PowerManager:
    """
    Controls the Linux CPU frequency governor based on interaction mode.

    All public methods return False and log at DEBUG level when the
    cpufreq interface is unavailable so callers need not guard the calls.
    """

    def __init__(self):
        paths = _governor_paths()
        self._available = bool(paths)
        self._current_governor: Optional[str] = None
        if self._available:
            # Read actual current governor so we track reality from the start
            self._current_governor = self._read_governor()
            logger.debug(
                "PowerManager: initialised — governor=%s, cores=%d",
                self._current_governor,
                len(paths),
            )
        else:
            logger.debug("PowerManager: cpufreq sysfs not available — governor control disabled")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True if the cpufreq sysfs interface was found at construction."""
        return self._available

    @property
    def current_governor(self) -> Optional[str]:
        """Last governor string successfully written, or None."""
        return self._current_governor

    def apply_for_mode(self, mode: InteractionMode) -> bool:
        """
        Set the CPU governor appropriate for *mode*.

        Returns True if the governor was set (or was already correct),
        False if unavailable or permission denied.
        """
        governor = _GOVERNOR_MAP.get(mode)
        if governor is None:
            logger.warning("PowerManager: no governor mapping for mode %s", mode)
            return False
        return self.set_governor(governor)

    def set_governor(self, governor: str) -> bool:
        """
        Write *governor* to every CPU core.

        Returns True when at least one core was updated successfully.
        """
        if not self._available:
            return False
        if governor == self._current_governor:
            return True  # Nothing to do

        paths = _governor_paths()
        if not paths:
            self._available = False
            return False

        success = 0
        for path in paths:
            try:
                path.write_text(governor)
                success += 1
            except (OSError, PermissionError) as exc:
                logger.debug("PowerManager: cannot write %s: %s", path, exc)

        if success:
            self._current_governor = governor
            logger.info(
                "PowerManager: governor → %s (%d/%d cores)",
                governor, success, len(paths),
            )
            return True

        logger.debug("PowerManager: could not set governor — no write permission")
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_governor(self) -> Optional[str]:
        """Read the current governor from the first CPU core."""
        paths = _governor_paths()
        if not paths:
            return None
        try:
            return paths[0].read_text().strip()
        except OSError:
            return None
