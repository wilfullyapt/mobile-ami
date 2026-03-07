import time
import threading
import logging
from typing import Callable, Optional

from agents.tools.base_tool import BaseTool, ToolParam

logger = logging.getLogger(__name__)


class TimerTool(BaseTool):
    """
    Starts a countdown timer and announces completion via TTS.
    The on_speak callback is injected so the tool can announce events
    without depending directly on the TTS or orchestrator.
    """

    name = "set_timer"
    description = "Start a countdown timer for a given number of minutes and announce when it completes."
    parameters = [
        ToolParam("minutes", "integer", "Duration of the timer in minutes", required=True),
        ToolParam("label", "string", "Optional label for the timer (e.g. 'focus block')", required=False),
    ]

    def __init__(self, on_speak: Optional[Callable[[str], None]] = None):
        self._on_speak = on_speak or (lambda text: logger.info("TTS: %s", text))

    def execute(self, minutes: int, label: str = "timer") -> str:
        threading.Thread(
            target=self._run,
            args=(int(minutes), label),
            daemon=True,
        ).start()
        return f"Started {minutes}-minute {label}."

    def _run(self, minutes: int, label: str):
        self._on_speak(f"Starting {minutes} minute {label}.")
        time.sleep(minutes * 60)
        self._on_speak(f"{label.capitalize()} complete. Take a break!")
