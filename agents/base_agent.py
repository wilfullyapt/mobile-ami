from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.model_orchestrator import ModelOrchestrator
    from agents.tools.tool_registry import ToolRegistry
    from agents.tools.base_tool import BaseTool
    from core.ami_paths import AmiPaths
    from core.agent_context import AgentContext


class BaseAgent(ABC):
    """
    Abstract base for all agents.

    Agents receive the ModelOrchestrator so they can access any model
    (e.g. LLM, TTS) without hard-coding dependencies. They also receive
    a ToolRegistry so the LLM can call registered tools.

    The optional ``paths`` argument gives agents access to the ~/.amini/ data
    directory tree (calendar, shopping list, messages, etc.). Family agents
    that persist data should store it under paths.data_dir.

    Lifecycle hooks ``on_entry`` and ``on_exit`` are called by AgentManager
    when the active agent changes. The shared AgentContext is passed to both
    hooks and to ``process()``. All three default to no-ops so existing
    subclasses need no changes.
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

    # ------------------------------------------------------------------
    # Lifecycle hooks — override to react to agent switching
    # ------------------------------------------------------------------

    def on_entry(self, context: "Optional[AgentContext]") -> None:
        """Called when this agent becomes the active agent."""

    def on_exit(self, context: "Optional[AgentContext]") -> None:
        """Called when this agent is about to be replaced by another."""

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    @abstractmethod
    def process(
        self,
        text: str,
        speaker: Optional[str] = None,
        context: "Optional[AgentContext]" = None,
    ) -> str:
        """
        Process a user utterance and return a spoken response.

        ``speaker`` is the display name of the identified family member
        (e.g. "Mom", "Jake") or None if speaker identification is not
        configured or the voice was not recognised. Agents should use this
        to personalise responses where appropriate.

        ``context`` is the shared AgentContext. When provided, agents should
        read recent history for continuity and append their response so other
        agents see a consistent conversation log. Defaults to None so all
        existing agent subclasses remain unaffected.
        """

    def get_tools(self) -> list["BaseTool"]:
        """
        Return the tools this agent exposes to the LLM.
        Override in subclasses to add tool-calling capability.
        """
        return []

    # ------------------------------------------------------------------
    # Ally mode interface — override in AllyAgent (and compatible plugins)
    # ------------------------------------------------------------------

    def interval_listen(
        self,
        notes: list,
        context: "Optional[AgentContext]" = None,
    ) -> Optional[str]:
        """
        Called every check_interval_sec with accumulated AmbientNotes.

        Return a spoken message string to insert autonomously, or None to
        remain silent. Default implementation: always silent (not ally-eligible).
        """
        return None

    def daily_update(self, context: "Optional[AgentContext]" = None) -> None:
        """
        Called once per day (typically at 03:00) for self-reflection and
        memory/soul updates. Default: no-op.
        """

    @classmethod
    def supports_ally_mode(cls) -> bool:
        """
        True if this agent class overrides ``interval_listen``.

        Used by AgentManager / UI to show which agents are ally-eligible.
        """
        return cls.interval_listen is not BaseAgent.interval_listen
