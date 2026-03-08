from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.model_orchestrator import ModelOrchestrator
    from agents.tools.tool_registry import ToolRegistry
    from agents.tools.base_tool import BaseTool
    from core.ami_paths import AmiPaths


class BaseAgent(ABC):
    """
    Abstract base for all agents.

    Agents receive the ModelOrchestrator so they can access any model
    (e.g. LLM, TTS) without hard-coding dependencies. They also receive
    a ToolRegistry so the LLM can call registered tools.

    The optional ``paths`` argument gives agents access to the ~/.amini/ data
    directory tree (calendar, shopping list, messages, etc.). Family agents
    that persist data should store it under paths.data_dir.
    """

    def __init__(
        self,
        orchestrator: "ModelOrchestrator",
        tool_registry: "ToolRegistry",
        paths: "Optional[AmiPaths]" = None,
    ):
        self._orchestrator = orchestrator
        self._tool_registry = tool_registry
        self._paths = paths

    @abstractmethod
    def process(self, text: str, speaker: Optional[str] = None) -> str:
        """
        Process a user utterance and return a spoken response.

        ``speaker`` is the display name of the identified family member
        (e.g. "Mom", "Jake") or None if speaker identification is not
        configured or the voice was not recognised. Agents should use this
        to personalise responses where appropriate.
        """

    def get_tools(self) -> list["BaseTool"]:
        """
        Return the tools this agent exposes to the LLM.
        Override in subclasses to add tool-calling capability.
        """
        return []
