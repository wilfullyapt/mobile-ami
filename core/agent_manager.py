import importlib
import importlib.util
import json
import logging
from typing import TYPE_CHECKING, Optional

from core.models.orchestrator import ModelOrchestrator
from agents.tools.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from core.ami_paths import AmiPaths
    from core.agent_context import AgentContext

logger = logging.getLogger(__name__)

# Built-in agents shipped with the project — always available.
_BUILTIN: dict[str, str] = {
    # Primary selectable agents
    "llm_response": "agents.llm_response_agent.LLMResponseAgent",
    "planning":     "agents.planning_agent.PlanningAgent",
    "block_timer":  "agents.block_timer_agent.BlockTimerAgent",
    # Backward-compat alias — "qa" resolves to LLMResponseAgent
    "qa":           "agents.llm_response_agent.LLMResponseAgent",
    # Family agents
    "family_scheduler": "agents.family_scheduler_agent.FamilySchedulerAgent",
    "shopping_list":    "agents.shopping_list_agent.ShoppingListAgent",
    "kids_story":       "agents.kids_story_agent.KidsStoryAgent",
    "morning_briefing": "agents.morning_briefing_agent.MorningBriefingAgent",
    "family_intercom":  "agents.family_intercom_agent.FamilyIntercomAgent",
}


class AgentManager:
    """
    Manages named agents and tracks which one is currently active.

    Loads agents from two sources (in priority order):
      1. Built-ins defined in _BUILTIN (shipped with the project)
      2. Plugin agents installed to ~/.amini/agents/<name>/ by AddonInstaller

    Each agent receives the shared ModelOrchestrator and ToolRegistry so it can
    access models and execute tools. The active agent is cycled with cycle().

    Lifecycle hooks ``on_entry`` / ``on_exit`` are fired on the old and new
    agents whenever the active agent changes (via cycle() or set_agent()).
    The optional ``context`` is forwarded to those hooks.
    """

    def __init__(
        self,
        slugs: list[str],
        orchestrator: ModelOrchestrator,
        tool_registry: ToolRegistry,
        paths: "Optional[AmiPaths]" = None,
        context: "Optional[AgentContext]" = None,
    ):
        self._slugs = slugs
        self._index = 0
        self._paths = paths
        self._context = context
        self._instances = {
            s: self._load(s, orchestrator, tool_registry)
            for s in slugs
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current(self) -> str:
        return self._slugs[self._index]

    @property
    def slugs(self) -> list[str]:
        return list(self._slugs)

    def cycle(self) -> None:
        old_agent = self._instances[self.current]
        old_agent.on_exit(self._context)
        self._index = (self._index + 1) % len(self._slugs)
        new_agent = self._instances[self.current]
        new_agent.on_entry(self._context)

    def set_agent(self, slug: str) -> None:
        """Switch the active agent by slug. Raises ValueError if unknown."""
        if slug not in self._slugs:
            raise ValueError(f"Unknown agent: {slug!r}")
        old_agent = self._instances[self.current]
        old_agent.on_exit(self._context)
        self._index = self._slugs.index(slug)
        new_agent = self._instances[self.current]
        new_agent.on_entry(self._context)

    def inject(self, slug: str, agent_instance) -> None:
        """
        Register a pre-built agent instance.

        Use this for agents that need special construction (e.g. AllyAgent
        which requires SoulManager, OwnerManager, and AllyListener injected
        at runtime). If ``slug`` is not already in the slug list it is appended;
        if it is already registered, the instance is replaced in-place.
        """
        if slug not in self._slugs:
            self._slugs.append(slug)
        self._instances[slug] = agent_instance

    def get_current_agent(self):
        return self._instances[self.current]

    # ------------------------------------------------------------------
    # Agent loading
    # ------------------------------------------------------------------

    def _load(self, slug: str, orchestrator, tool_registry):
        # 1. Built-in agents — import from the agents package
        if slug in _BUILTIN:
            dotted, class_name = _BUILTIN[slug].rsplit(".", 1)
            module = importlib.import_module(dotted)
            return getattr(module, class_name)(orchestrator, tool_registry, self._paths)

        # 2. Plugin agents from ~/.amini/agents/<slug>/
        if self._paths is not None:
            agent_py = self._paths.agent_module(slug)
            manifest_path = self._paths.agent_manifest(slug)
            if agent_py.exists() and manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                spec = importlib.util.spec_from_file_location(
                    f"amini_agent_{slug}", agent_py
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                cls = getattr(module, manifest["entry_class"])
                logger.info("Loaded plugin agent '%s' from %s", slug, agent_py)
                return cls(orchestrator, tool_registry, self._paths)

        raise KeyError(
            f"Unknown agent: '{slug}' — not a built-in and not found in ~/.amini/agents/"
        )
