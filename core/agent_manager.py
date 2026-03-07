from agents.qa_agent import QAAgent
from agents.block_timer_agent import BlockTimerAgent
from core.model_orchestrator import ModelOrchestrator
from agents.tools.tool_registry import ToolRegistry


class AgentManager:
    """
    Manages a set of named agents and tracks which one is currently active.

    Each agent is instantiated with the shared ModelOrchestrator and ToolRegistry
    so they can access models and execute tools.
    """

    _registry = {
        "qa": QAAgent,
        "block_timer": BlockTimerAgent,
    }

    def __init__(self, slugs: list[str], orchestrator: ModelOrchestrator, tool_registry: ToolRegistry):
        self._slugs = slugs
        self._index = 0
        self._instances = {
            s: self._registry[s](orchestrator, tool_registry)
            for s in slugs
        }

    @property
    def current(self) -> str:
        return self._slugs[self._index]

    def cycle(self):
        self._index = (self._index + 1) % len(self._slugs)

    def get_current_agent(self):
        return self._instances[self.current]
