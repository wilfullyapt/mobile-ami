"""
TimerSubAgent — countdown timers with TTS announcements.

Primary tool:    set_timer(minutes, label="timer")
Additional tool: cancel_timer(label)

Uses name = "set_timer" so it is a drop-in replacement for the old
TimerTool; BlockTimerAgent continues to work unchanged.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable, Optional

from agents.base_sub_agent import BaseSubAgent
from agents.tools.base_tool import BaseTool, ToolParam

if TYPE_CHECKING:
    from core.models.orchestrator import ModelOrchestrator
    from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)


class _CancelTimerTool(BaseTool):
    name = "cancel_timer"
    description = "Cancel a running timer by its label."
    parameters = [
        ToolParam("label", "string", "The label of the timer to cancel", required=True),
    ]

    def __init__(self, timers: dict[str, threading.Event]):
        self._timers = timers

    def execute(self, label: str = "timer") -> str:
        event = self._timers.get(label)
        if event is None:
            return f"No running timer with label '{label}'."
        event.set()
        return f"Timer '{label}' cancelled."


class TimerSubAgent(BaseSubAgent):
    """
    Starts countdown timers and announces completion via TTS.

    ``name = "set_timer"`` maintains backward compatibility with code that
    references the old TimerTool by name.
    """

    name = "set_timer"
    description = "Start a countdown timer for a given number of minutes and announce when it completes."
    parameters = [
        ToolParam("minutes", "integer", "Duration of the timer in minutes", required=True),
        ToolParam("label", "string", "Optional label for the timer (e.g. 'focus block')", required=False),
    ]

    def __init__(
        self,
        orchestrator: "ModelOrchestrator",
        paths: "Optional[AmiPaths]" = None,
        on_speak: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(orchestrator, paths)
        self._on_speak = on_speak or (lambda text: logger.info("TTS: %s", text))
        self._timers: dict[str, threading.Event] = {}

    def execute(self, minutes: int, label: str = "timer") -> str:
        stop_event = threading.Event()
        self._timers[label] = stop_event
        threading.Thread(
            target=self._run,
            args=(int(minutes), label, stop_event),
            daemon=True,
        ).start()
        return f"Started {minutes}-minute {label}."

    def _run(self, minutes: int, label: str, stop_event: threading.Event) -> None:
        self._on_speak(f"Starting {minutes} minute {label}.")
        cancelled = stop_event.wait(timeout=minutes * 60)
        self._timers.pop(label, None)
        if not cancelled:
            self._on_speak(f"{label.capitalize()} complete. Take a break!")

    def get_additional_tools(self) -> list[BaseTool]:
        return [_CancelTimerTool(self._timers)]
