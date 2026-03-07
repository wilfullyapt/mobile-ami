from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.model_orchestrator import ModelOrchestrator
    from agents.tools.tool_registry import ToolRegistry
    from agents.tools.base_tool import BaseTool


class BaseAgent(ABC):
    """
    Abstract base for all agents.

    Agents receive the ModelOrchestrator so they can access any model
    (e.g. LLM, TTS) without hard-coding dependencies. They also receive
    a ToolRegistry so the LLM can call registered tools.
    """

    def __init__(self, orchestrator: "ModelOrchestrator", tool_registry: "ToolRegistry"):
        self._orchestrator = orchestrator
        self._tool_registry = tool_registry

    @abstractmethod
    def process(self, text: str) -> str:
        """Process a user utterance and return a spoken response."""

    def get_tools(self) -> list["BaseTool"]:
        """
        Return the tools this agent exposes to the LLM.
        Override in subclasses to add tool-calling capability.
        """
        return []
