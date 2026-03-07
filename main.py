import yaml
import threading
import time
import os
from hardware.buttons import DeviceButtons
from hardware.display import StatusDisplay
from hardware.network_manager import NetworkManager
from hardware.power import get_battery
from hardware.leds import LEDs
from hardware.audio import AudioManager
from core.updater import AutoUpdater
from core.agent_manager import AgentManager
from core.wake_detector import WakeDetector
from core.vad import VAD
from core.stt import STT
from core.llm import LLM
from core.tts import TTS
from agents.base_agent import BaseAgent

class VoiceAssistant:
    def __init__(self):
        with open("config.yaml") as f:
            self.config = yaml.safe_load(f)

        self.display = StatusDisplay()
        self.network = NetworkManager()
        self.leds = LEDs()
        self.audio = AudioManager()
        self.power = get_battery
        self.updater = AutoUpdater(self.network, self.config)
        self.agent_manager = AgentManager(["qa", "block_timer"])
        self.buttons = DeviceButtons(self.config, self.display, self.network, self)
        self.wake_detector = WakeDetector()
        self.vad = VAD()
        self.stt = STT()
        self.llm = LLM()
        self.tts = TTS()

        self.current_mode = "hotword"
        self.is_listening = False

        # Background threads
        threading.Thread(target=self._status_loop, daemon=True).start()
        threading.Thread(target=self._wake_loop, daemon=True).start()

        self.display.update(50, 4.1, "connected", "HomeWiFi", self.agent_manager.current, "Ready")
        self.leds.set_color("green")
        self.updater.mark_as_healthy()

    def _status_loop(self):
        while True:
            bat, volt = self.power()
            self.display.update(bat, volt, self.network.state, self.network.ssid, self.agent_manager.current)
            time.sleep(30)

    def _wake_loop(self):
        while True:
            if self.current_mode == "hotword" and not self.is_listening:
                audio_chunk = self.audio.get_chunk()
                if self.wake_detector.detect(audio_chunk):
                    self.trigger_listening()
            time.sleep(0.05)

    def trigger_listening(self):
        self.is_listening = True
        self.leds.set_color("blue")
        self.tts.speak("Listening")
        audio = self.audio.record_until_silence(self.vad)
        text = self.stt.transcribe(audio)
        if text:
            agent = self.agent_manager.get_current_agent()
            response = agent.process(text)
            self.tts.speak(response)
        self.is_listening = False
        self.leds.set_color("green")

    def action_click_handler(self):
        if self.current_mode == "manual":
            self.trigger_listening()

    def cycle_agent(self):
        self.agent_manager.cycle()
        self.display.update_mode(self.agent_manager.current)

    def graceful_shutdown(self):
        self.tts.speak("Shutting down")
        self.leds.set_color("red")
        time.sleep(2)
        os.system("sudo systemctl poweroff")

if __name__ == "__main__":
    app = VoiceAssistant()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting")
