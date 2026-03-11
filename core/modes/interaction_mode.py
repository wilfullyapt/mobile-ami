"""
Interaction mode management.

Three modes control how the device listens for voice input:

    MANUAL    — the user must press the action button to trigger a listen cycle.
                Quiet and unobtrusive; good for meetings or focus work.

    HOT_WORD  — the wake word activates the listen pipeline (default).
                Standard always-on assistant behaviour.

    ALLY      — ambient passive listening plus autonomous proactive insertion.
                The ally agent evaluates ambient context at a configurable
                interval and may speak up when it has something useful to say.
                The wake word and action button still work in this mode.

Mode is persisted to ~/.amini/settings.json so it survives reboots.
The first-boot default is read from config.yaml (ally.interaction_mode).

Cycling order (interaction button hold):
    MANUAL → HOT_WORD → ALLY → MANUAL → ...
"""

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.ami_paths import AmiPaths


class InteractionMode(str, Enum):
    MANUAL = "manual"
    HOT_WORD = "hot_word"
    ALLY = "ally"


_CYCLE_ORDER = [InteractionMode.MANUAL, InteractionMode.HOT_WORD, InteractionMode.ALLY]

_MODE_LABELS = {
    InteractionMode.MANUAL: "Manual mode — press action button to listen",
    InteractionMode.HOT_WORD: "Hot-word mode — say the wake word to activate",
    InteractionMode.ALLY: "Ally mode — I'm listening and may speak up",
}


class ModeManager:
    """
    Manages the current interaction mode with persistence.

    Backward-compatible with the old ``hotword_trigger`` boolean setting:
    if ``interaction_mode`` is not in settings.json, it falls back to
    reading ``hotword_trigger`` so existing installations continue working.
    """

    def __init__(self, paths: "AmiPaths", default: InteractionMode = InteractionMode.HOT_WORD):
        self._paths = paths
        settings = paths.load_settings()

        if "interaction_mode" in settings:
            raw = settings["interaction_mode"]
        elif "hotword_trigger" in settings:
            # Migrate from old boolean setting
            raw = InteractionMode.HOT_WORD.value if settings["hotword_trigger"] else InteractionMode.MANUAL.value
        else:
            raw = default.value

        try:
            self._mode = InteractionMode(raw)
        except ValueError:
            self._mode = default

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def mode(self) -> InteractionMode:
        return self._mode

    @property
    def label(self) -> str:
        """Human-readable description of the current mode, suitable for TTS."""
        return _MODE_LABELS.get(self._mode, self._mode.value)

    def cycle(self) -> InteractionMode:
        """Advance to the next mode in the cycle order and persist."""
        idx = _CYCLE_ORDER.index(self._mode)
        self._mode = _CYCLE_ORDER[(idx + 1) % len(_CYCLE_ORDER)]
        self._persist()
        return self._mode

    def set(self, mode: InteractionMode) -> None:
        """Set a specific mode and persist."""
        self._mode = InteractionMode(mode) if isinstance(mode, str) else mode
        self._persist()

    def is_manual(self) -> bool:
        return self._mode == InteractionMode.MANUAL

    def is_hot_word(self) -> bool:
        return self._mode == InteractionMode.HOT_WORD

    def is_ally(self) -> bool:
        return self._mode == InteractionMode.ALLY

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        settings = self._paths.load_settings()
        settings["interaction_mode"] = self._mode.value
        # Keep hotword_trigger in sync for backward compat
        settings["hotword_trigger"] = self._mode != InteractionMode.MANUAL
        self._paths.save_settings(settings)
