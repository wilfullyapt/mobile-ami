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

from core.agent_context import AgentContext
from core.ami_paths import AmiPaths
from core.addon_installer import AddonInstaller
from core.conversation_logger import ConversationLogger
from core.modes.interaction_mode import InteractionMode, ModeManager
from core.models.registry import ModelRegistry, ModelRole
from core.models.orchestrator import ModelOrchestrator
from core.agent_manager import AgentManager
from core.server.device_server import DeviceServer
from core.eval_day import EvalDay
from core.owner_manager import OwnerManager
from core.pipeline import VoicePipeline
from core.modes.power_manager import PowerManager
from core.process_bus import BusEvent, ProcessBus
from core.server.job_manager import JobManager
from core.ally.soul import SoulManager
from core.updater import AutoUpdater
from core.voice_profiles import VoiceProfileManager

from agents.ally_agent import AllyAgent
from agents.tools.tool_registry import ToolRegistry
from agents.base_sub_agent import register_sub_agent
from agents.subagents.memory_subagent import MemorySubAgent
from agents.subagents.timer_subagent import TimerSubAgent
from agents.subagents.hardware_subagent import HardwareSubAgent
from agents.subagents.updater_subagent import UpdaterSubAgent
from agents.subagents.conversation_subagent import ConversationSubAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class VoiceAssistant:
    def __init__(self, paths: AmiPaths = None):
        with open("config.yaml") as f:
            self.config = yaml.safe_load(f)

        # ── User data directory (~/.amini/) ────────────────────────────
        self.paths = paths or AmiPaths()
        self.paths.ensure_dirs()

        ally_cfg: dict = self.config.get("ally", {})

        # ── Interaction mode ───────────────────────────────────────────
        default_mode_raw = ally_cfg.get("interaction_mode", "hot_word")
        try:
            default_mode = InteractionMode(default_mode_raw)
        except ValueError:
            default_mode = InteractionMode.HOT_WORD
        self.mode_manager = ModeManager(self.paths, default=default_mode)

        # ── Owner + soul ───────────────────────────────────────────────
        self.owner_manager = OwnerManager(self.paths)
        self.soul_manager = SoulManager(self.paths)

        # Seed a soul.md if the owner is already known but the file doesn't exist
        if self.owner_manager.has_owner and not self.soul_manager.exists():
            self.soul_manager.create_for_owner(self.owner_manager.owner_name)

        # ── Voice profiles ─────────────────────────────────────────────
        self.voice_profiles = VoiceProfileManager(self.paths.profiles_dir)

        # ── Model layer ────────────────────────────────────────────────
        registry = ModelRegistry(self.config["models"], self.paths)
        self.orchestrator = ModelOrchestrator(registry)
        self.orchestrator.preload_eager()   # loads VAD + wake detector at startup
        self.orchestrator.preload_for_mode(self.mode_manager.mode)

        # ── Power management ───────────────────────────────────────────
        self.power_manager = PowerManager()
        self.power_manager.apply_for_mode(self.mode_manager.mode)

        # ── IPC bus ────────────────────────────────────────────────────
        self.bus = ProcessBus()

        # ── Hardware layer (before tools so sub-agents can hold refs) ──
        dev_cfg = self.config.get("device", {})
        self.display = StatusDisplay(timeout_sec=dev_cfg.get("display_timeout_sec", 15))
        self.network = NetworkManager(self.config)
        self.leds = LEDs()
        self.audio = AudioManager()
        self.updater = AutoUpdater(self.network, self.config)

        # ── Shared agent context ───────────────────────────────────────
        self.agent_context = AgentContext.empty()
        self.agent_context.set_flag("interaction_mode", self.mode_manager.mode.value)

        # ── Tool / sub-agent layer ─────────────────────────────────────
        self.tool_registry = ToolRegistry()

        register_sub_agent(
            self.tool_registry,
            MemorySubAgent(self.orchestrator, self.paths),
        )
        register_sub_agent(
            self.tool_registry,
            TimerSubAgent(
                self.orchestrator,
                self.paths,
                on_speak=self._tts_speak,
            ),
        )
        register_sub_agent(
            self.tool_registry,
            HardwareSubAgent(
                self.orchestrator,
                self.paths,
                network=self.network,
                leds=self.leds,
            ),
        )
        self._installer = AddonInstaller(self.paths)
        register_sub_agent(
            self.tool_registry,
            UpdaterSubAgent(
                self.orchestrator,
                self.paths,
                installer=self._installer,
            ),
        )
        register_sub_agent(
            self.tool_registry,
            ConversationSubAgent(
                self.orchestrator,
                self.paths,
                context=self.agent_context,
            ),
        )

        # ── Agent layer — config-driven exposed list + installed plugins ─
        agents_cfg = self.config.get("agents", {})
        exposed = agents_cfg.get("exposed", None)
        if exposed:
            installed = self.paths.list_agents()
            all_slugs = exposed + [s for s in installed if s not in exposed]
        else:
            all_slugs = [
                "llm_response", "planning", "block_timer",
                "family_scheduler", "shopping_list",
                "kids_story", "morning_briefing", "family_intercom",
            ]
            installed = self.paths.list_agents()
            all_slugs += [s for s in installed if s not in all_slugs]

        self.agent_manager = AgentManager(
            slugs=all_slugs,
            orchestrator=self.orchestrator,
            tool_registry=self.tool_registry,
            paths=self.paths,
            context=self.agent_context,
        )

        # ── Ally agent (injected — needs soul/owner/listener at runtime) ─
        self._ally_listener = None  # built lazily when entering ALLY mode

        self.ally_agent = AllyAgent(
            orchestrator=self.orchestrator,
            tool_registry=self.tool_registry,
            paths=self.paths,
            soul_manager=self.soul_manager,
            owner_manager=self.owner_manager,
            on_owner_established=self._on_owner_established,
            ally_listener=None,  # wired in when ally mode starts
            voice_profiles=self.voice_profiles,
            ally_config=ally_cfg,
        )
        self.agent_manager.inject("ally", self.ally_agent)

        # ── Conversation logger ────────────────────────────────────────
        self.conv_logger = ConversationLogger(self.paths)

        # ── Async job manager ──────────────────────────────────────────
        self.job_manager = JobManager()

        # ── Device server ───────────────────────────────────────────────
        srv_cfg = self.config.get("device_server", {})
        if srv_cfg.get("enabled", True):
            self.server = DeviceServer(
                port=srv_cfg.get("port", 5000),
                voice_assistant=self,
                addon_installer=self._installer,
                conv_logger=self.conv_logger,
                job_manager=self.job_manager,
            )
            self.network.add_state_change_callback(self._on_network_state_change)
        else:
            self.server = None

        # ── EvalDay ────────────────────────────────────────────────────
        self.eval_day = EvalDay(
            paths=self.paths,
            orchestrator=self.orchestrator,
            soul_manager=self.soul_manager,
            ally_config=ally_cfg,
            ally_agent=self.ally_agent,
        )

        # ── Buttons ────────────────────────────────────────────────────
        self.buttons = DeviceButtons(self.config, self.display, self.network, self)

        # ── Pipeline ───────────────────────────────────────────────────
        self.pipeline = VoicePipeline(
            orchestrator=self.orchestrator,
            agent_manager=self.agent_manager,
            audio=self.audio,
            leds=self.leds,
            on_speak=self._tts_speak,
            conv_logger=self.conv_logger,
            voice_profiles=self.voice_profiles,
            agent_context=self.agent_context,
        )

        # ── Background threads ─────────────────────────────────────────
        threading.Thread(target=self._status_loop, daemon=True).start()
        self.eval_day.start()

        self.display.update(
            50, 4.1, "offline", "", self.agent_manager.current,
            interaction_mode=self.mode_manager.mode.value,
        )
        self.leds.set_color("green")
        self.updater.mark_as_healthy()
        logger.info("Interaction mode: %s", self.mode_manager.mode.value)

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
                interaction_mode=self.mode_manager.mode.value,
                has_internet=self.network.has_internet(),
                update_pending=self.updater.update_pending,
            )
            time.sleep(30)

    # ------------------------------------------------------------------
    # Entry point — mode-aware main loop
    # ------------------------------------------------------------------

    def run(self):
        mode = self.mode_manager.mode

        if mode == InteractionMode.ALLY:
            self._start_ally_mode()
            # Wake word still active in ally mode for explicit interactions
            self.pipeline.wake_loop(self.audio.get_chunk)

        elif mode == InteractionMode.HOT_WORD:
            self.pipeline.wake_loop(self.audio.get_chunk)

        else:  # MANUAL — button-only; just keep process alive
            while True:
                time.sleep(1)

    # ------------------------------------------------------------------
    # Ally mode lifecycle
    # ------------------------------------------------------------------

    def _start_ally_mode(self):
        """Build and start the AllyListener; wire it into AllyAgent."""
        from core.ally.listener import AllyListener

        listener = AllyListener(
            orchestrator=self.orchestrator,
            audio=self.audio,
            voice_profiles=self.voice_profiles,
            owner_name=self.owner_manager.owner_name,
            ally_config=self.config.get("ally", {}),
            on_context_ready=self._on_ally_context_ready,
            paths=self.paths,
        )
        self._ally_listener = listener
        self.ally_agent._listener = listener
        listener.start()
        logger.info("Ally mode: ambient listening started")

    def _stop_ally_mode(self):
        if self._ally_listener is not None:
            self._ally_listener.stop()
            self.ally_agent._listener = None
            self._ally_listener = None

    def _on_ally_context_ready(self, listener):
        """
        Called by AllyListener every check_interval_sec.
        Uses interval_listen to review ambient notes and optionally speak.
        """
        pending_notes = listener.get_pending_notes()
        message = self.ally_agent.interval_listen(pending_notes, self.agent_context)
        if message:
            logger.info("Ally autonomous insertion: %s", message[:80])
            self.leds.set_color("blue")
            self._tts_speak(message)
            self.leds.set_color("green")

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def trigger_listening(self):
        """
        Always triggers one listen cycle, regardless of interaction mode.
        Runs in a background thread so it doesn't block the button callback.
        """
        threading.Thread(target=self.pipeline.run_once, daemon=True).start()

    def cycle_agent(self):
        self.agent_manager.cycle()
        self.display.update_mode(self.agent_manager.current)

    def cycle_mode(self):
        """
        Cycle interaction mode: manual → hot_word → ally → manual.
        Manages AllyListener lifecycle, CPU governor, and model preloading
        on each transition.
        """
        old_mode = self.mode_manager.mode
        new_mode = self.mode_manager.cycle()
        logger.info("Mode: %s → %s", old_mode.value, new_mode.value)

        if old_mode == InteractionMode.ALLY and new_mode != InteractionMode.ALLY:
            self._stop_ally_mode()

        if new_mode == InteractionMode.ALLY and old_mode != InteractionMode.ALLY:
            self._start_ally_mode()

        # Apply CPU governor and preload models for the new mode
        self.power_manager.apply_for_mode(new_mode)
        self.orchestrator.preload_for_mode(new_mode)
        self.agent_context.set_flag("interaction_mode", new_mode.value)
        self.bus.publish(BusEvent.MODE_CHANGE, payload=new_mode.value, source="main")

        self._tts_speak(self.mode_manager.label)
        self.display.update_mode(self.agent_manager.current, interaction_mode=new_mode.value)

    # ------------------------------------------------------------------
    # Owner establishment callback (fired by AllyAgent)
    # ------------------------------------------------------------------

    def _on_owner_established(self, name: str):
        """
        Persists the new owner, creates SOUL.md, and updates the
        AllyListener's owner_name so future utterances are tagged correctly.
        """
        self.owner_manager.establish(name)
        if not self.soul_manager.exists():
            self.soul_manager.create_for_owner(name)
        if self._ally_listener is not None:
            self._ally_listener._owner_name = name
        logger.info("Owner established: %s", name)

    def graceful_shutdown(self):
        self._tts_speak("Shutting down")
        self.leds.set_color("red")
        self._stop_ally_mode()
        self.eval_day.stop()
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
        absent_threshold = self.config.get("ally", {}).get("owner_absent_threshold_sec", 300)
        return {
            "battery_pct": bat,
            "voltage": volt,
            "agent": self.agent_manager.current,
            "agents": self.agent_manager.slugs,
            "net_state": self.network.state,
            "ssid": self.network.ssid,
            "has_internet": self.network.has_internet(),
            "interaction_mode": self.mode_manager.mode.value,
            "owner": self.owner_manager.owner_name,
            "owner_present": self.owner_manager.is_owner_present(within_sec=absent_threshold),
            "ally_listening": self._ally_listener is not None and self._ally_listener.is_running,
        }

    def get_settings(self) -> dict:
        return self.paths.load_settings()

    def update_setting(self, key: str, value) -> None:
        settings = self.paths.load_settings()
        settings[key] = value
        self.paths.save_settings(settings)


if __name__ == "__main__":
    app = VoiceAssistant()
    try:
        app.run()
    except KeyboardInterrupt:
        logger.info("Interrupted — shutting down")
        app._stop_ally_mode()
        app.eval_day.stop()
        app.orchestrator.shutdown()
