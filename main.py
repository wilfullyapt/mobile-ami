import logging
import os
import threading
import time

import yaml

from hardware.audio import AudioManager
from hardware.buttons import DeviceButtons
from hardware.display import StatusDisplay
from hardware.leds import LEDs
from hardware.network_manager import NetworkManager
from hardware.power import get_battery

from core.ami_paths import AmiPaths
from core.model_registry import ModelRegistry, ModelRole
from core.model_orchestrator import ModelOrchestrator
from core.agent_manager import AgentManager
from core.device_server import DeviceServer
from core.pipeline import VoicePipeline
from core.updater import AutoUpdater

from agents.tools.tool_registry import ToolRegistry
from agents.tools.timer_tool import TimerTool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class VoiceAssistant:
    def __init__(self, paths: AmiPaths = None):
        with open("config.yaml") as f:
            self.config = yaml.safe_load(f)

        # ── User data directory (~/.amini/) ────────────────────────────
        self.paths = paths or AmiPaths()
        self.paths.ensure_dirs()

        # ── Persistent settings ────────────────────────────────────────
        self._settings = self.paths.load_settings()
        if "hotword_trigger" not in self._settings:
            self._settings["hotword_trigger"] = True

        # ── Model layer ────────────────────────────────────────────────
        registry = ModelRegistry(self.config["models"], self.paths)
        self.orchestrator = ModelOrchestrator(registry)
        self.orchestrator.preload_eager()   # loads VAD + wake detector at startup

        # ── Tool layer ─────────────────────────────────────────────────
        self.tool_registry = ToolRegistry()
        self.tool_registry.register(TimerTool(on_speak=self._tts_speak))

        # ── Agent layer — built-ins + any plugins in ~/.amini/agents/ ──
        installed = self.paths.list_agents()
        all_slugs = ["qa", "block_timer"] + [s for s in installed if s not in ("qa", "block_timer")]
        self.agent_manager = AgentManager(
            slugs=all_slugs,
            orchestrator=self.orchestrator,
            tool_registry=self.tool_registry,
            paths=self.paths,
        )

        # ── Hardware layer ─────────────────────────────────────────────
        dev_cfg = self.config.get("device", {})
        self.display = StatusDisplay(timeout_sec=dev_cfg.get("display_timeout_sec", 15))
        self.network = NetworkManager(self.config)
        self.leds = LEDs()
        self.audio = AudioManager()
        self.updater = AutoUpdater(self.network, self.config)

        # ── Device server ───────────────────────────────────────────────
        srv_cfg = self.config.get("device_server", {})
        if srv_cfg.get("enabled", True):
            self.server = DeviceServer(
                port=srv_cfg.get("port", 5000),
                voice_assistant=self,
            )
            self.network.add_state_change_callback(self._on_network_state_change)
        else:
            self.server = None

        # ── Buttons ────────────────────────────────────────────────────
        self.buttons = DeviceButtons(self.config, self.display, self.network, self)

        # ── Pipeline ───────────────────────────────────────────────────
        self.pipeline = VoicePipeline(
            orchestrator=self.orchestrator,
            agent_manager=self.agent_manager,
            audio=self.audio,
            leds=self.leds,
            on_speak=self._tts_speak,
        )

        # ── Background status thread ───────────────────────────────────
        threading.Thread(target=self._status_loop, daemon=True).start()

        self.display.update(50, 4.1, "offline", "", self.agent_manager.current, "Ready")
        self.leds.set_color("green")
        self.updater.mark_as_healthy()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _tts_speak(self, text: str):
        self.orchestrator.get(ModelRole.TTS).speak(text)

    # ------------------------------------------------------------------
    # Background threads
    # ------------------------------------------------------------------

    def _status_loop(self):
        while True:
            bat, volt = get_battery()
            self.display.update(
                bat, volt,
                self.network.state,
                self.network.ssid,
                self.agent_manager.current,
            )
            time.sleep(30)

    # ------------------------------------------------------------------
    # Entry point: blocking wake loop runs on main thread
    # ------------------------------------------------------------------

    def run(self):
        if self._settings.get("hotword_trigger", True):
            self.pipeline.wake_loop(self.audio.get_chunk)
        else:
            while True:
                time.sleep(1)

    # ------------------------------------------------------------------
    # Button handlers (called by DeviceButtons)
    # ------------------------------------------------------------------

    def trigger_listening(self):
        """Manual trigger: run one pipeline cycle immediately."""
        self.pipeline.run_once()

    def action_click_handler(self):
        if not self._settings.get("hotword_trigger", True):
            self.trigger_listening()

    def cycle_agent(self):
        self.agent_manager.cycle()
        self.display.update_mode(self.agent_manager.current)

    def graceful_shutdown(self):
        self._tts_speak("Shutting down")
        self.leds.set_color("red")
        self.orchestrator.shutdown()
        time.sleep(2)
        os.system("sudo systemctl poweroff")

    # ------------------------------------------------------------------
    # Network state change callback
    # ------------------------------------------------------------------

    def _on_network_state_change(self, new_state: str):
        if new_state in ("hotspot", "wifi"):
            if self.server:
                self.server.start()
            ip = self.network.get_device_ip()
            port = self.config.get("device_server", {}).get("port", 5000)
            url = f"http://{ip}:{port}"
            self.display.set_server_url(url)
        else:  # offline
            if self.server:
                self.server.stop()
            self.display.set_server_url(None)

    # ------------------------------------------------------------------
    # Device server API surface
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        bat, volt = get_battery()
        return {
            "battery_pct": bat,
            "voltage": volt,
            "agent": self.agent_manager.current,
            "agents": self.agent_manager._slugs,
            "net_state": self.network.state,
            "ssid": self.network.ssid,
            "has_internet": self.network.has_internet(),
            "hotword_trigger": self._settings.get("hotword_trigger", True),
        }

    def update_setting(self, key: str, value) -> None:
        self._settings[key] = value
        self.paths.save_settings(self._settings)


if __name__ == "__main__":
    app = VoiceAssistant()
    try:
        app.run()
    except KeyboardInterrupt:
        logger.info("Interrupted — shutting down")
        app.orchestrator.shutdown()
