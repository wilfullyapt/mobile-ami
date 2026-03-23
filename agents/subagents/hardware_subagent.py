"""
HardwareSubAgent — hardware status and control tools.

Primary tool:    get_battery_status()
Additional tools: get_network_status(), set_led_color(color)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from agents.base_sub_agent import BaseSubAgent
from agents.tools.base_tool import BaseTool, ToolParam

if TYPE_CHECKING:
    from core.models.orchestrator import ModelOrchestrator
    from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)


class _GetNetworkStatusTool(BaseTool):
    name = "get_network_status"
    description = "Get the current network state (offline, hotspot, or wifi) and SSID."
    parameters = []

    def __init__(self, network):
        self._network = network

    def execute(self) -> str:
        if self._network is None:
            return "Network status unavailable."
        state = getattr(self._network, "state", "unknown")
        ssid = getattr(self._network, "ssid", "")
        if ssid:
            return f"Network: {state} ({ssid})"
        return f"Network: {state}"


class _SetLedColorTool(BaseTool):
    name = "set_led_color"
    description = "Set the LED color on the device."
    parameters = [
        ToolParam("color", "string", "Color name (e.g. 'red', 'green', 'blue', 'yellow')", required=True),
    ]

    def __init__(self, leds):
        self._leds = leds

    def execute(self, color: str) -> str:
        if self._leds is None:
            return "LEDs unavailable."
        self._leds.set_color(color)
        return f"LED color set to {color}."


class HardwareSubAgent(BaseSubAgent):
    """Reports battery status and exposes network and LED controls."""

    slug = "hardware"
    display_name = "Hardware"
    name = "get_battery_status"
    description = "Get the current battery percentage and voltage."
    parameters = []

    def __init__(
        self,
        orchestrator: "ModelOrchestrator",
        paths: "Optional[AmiPaths]" = None,
        network=None,
        leds=None,
    ):
        super().__init__(orchestrator, paths)
        self._network = network
        self._leds = leds

    def execute(self) -> str:
        try:
            from hardware.power import get_battery
            pct, volt = get_battery()
            return f"Battery: {pct}% at {volt:.2f}V"
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_battery_status failed: %s", exc)
            return "Battery status unavailable."

    def get_additional_tools(self) -> list[BaseTool]:
        return [
            _GetNetworkStatusTool(self._network),
            _SetLedColorTool(self._leds),
        ]
