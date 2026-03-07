from agents.qa_agent import QAAgent
from agents.block_timer_agent import BlockTimerAgent

class AgentManager:
    _registry = {"qa": QAAgent, "block_timer": BlockTimerAgent}

    def __init__(self, slugs: list):
        self._slugs = slugs
        self._index = 0
        self._instances = {s: self._registry[s]() for s in slugs}

    @property
    def current(self):
        return self._slugs[self._index]

    def cycle(self):
        self._index = (self._index + 1) % len(self._slugs)

    def get_current_agent(self):
        return self._instances[self.current]
