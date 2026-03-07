import time
import threading
from agents.base_agent import BaseAgent
from core.tts import TTS

class BlockTimerAgent(BaseAgent):
    def __init__(self):
        self.tts = TTS()

    def process(self, text: str) -> str:
        if "start" in text.lower() and "minute" in text.lower():
            # parse minutes, start timer thread
            threading.Thread(target=self._run_timer, args=(25,), daemon=True).start()
            return "Starting 25-minute focus block"
        return "Timer command not recognized"

    def _run_timer(self, minutes):
        self.tts.speak(f"Starting {minutes} minute block")
        time.sleep(minutes * 60)
        self.tts.speak("Block complete. Take a break!")
