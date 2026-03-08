import importlib
import importlib.util
import json
import logging
from typing import TYPE_CHECKING, Optional

from core.model_orchestrator import ModelOrchestrator
from agents.tools.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)

# Built-in agents shipped with the project — always available.
_BUILTIN: dict[str, str] = {
    "qa": "agents.qa_agent.QAAgent",
    "block_timer": "agents.block_timer_agent.BlockTimerAgent",
    "family_scheduler": "agents.family_scheduler_agent.FamilySchedulerAgent",
    "shopping_list": "agents.shopping_list_agent.ShoppingListAgent",
    "kids_story": "agents.kids_story_agent.KidsStoryAgent",
    "morning_briefing": "agents.morning_briefing_agent.MorningBriefingAgent",
    "family_intercom": "agents.family_intercom_agent.FamilyIntercomAgent",
}


class AgentManager:
    """
    Manages named agents and tracks which one is currently active.

    Loads agents from two sources (in priority order):
      1. Built-ins defined in _BUILTIN (shipped with the project)
      2. Plugin agents installed to ~/.amini/agents/<name>/ by AddonInstaller

    Each agent receives the shared ModelOrchestrator and ToolRegistry so it can
    access models and execute tools. The active agent is cycled with cycle().
    """

    def __init__(
        self,
        slugs: list[str],
        orchestrator: ModelOrchestrator,
        tool_registry: ToolRegistry,
        paths: "Optional[AmiPaths]" = None,
    ):
        self._slugs = slugs
        self._index = 0
        self._paths = paths
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
        self._index = (self._index + 1) % len(self._slugs)

    def set_agent(self, slug: str) -> None:
        """Switch the active agent by slug. Raises ValueError if unknown."""
        if slug not in self._slugs:
            raise ValueError(f"Unknown agent: {slug!r}")
        self._index = self._slugs.index(slug)

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
