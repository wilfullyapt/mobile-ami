import importlib
import importlib.util
import json
import logging
from typing import TYPE_CHECKING, Optional

from core.models.orchestrator import ModelOrchestrator
from agents.tools.tool_registry import ToolRegistry, FilteredToolRegistry

if TYPE_CHECKING:
    from core.ami_paths import AmiPaths
    from core.agent_context import AgentContext
    from core.config_manager import ConfigManager

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

# Human-readable display names for built-in agents
_BUILTIN_DISPLAY: dict[str, str] = {
    "llm_response":     "General Q&A",
    "planning":         "Planning",
    "block_timer":      "Focus Timer",
    "qa":               "General Q&A (legacy)",
    "family_scheduler": "Family Scheduler",
    "shopping_list":    "Shopping List",
    "kids_story":       "Kids Stories",
    "morning_briefing": "Morning Briefing",
    "family_intercom":  "Family Intercom",
    "ally":             "Ally (Companion)",
}


class AgentManager:
    """
    Manages named agents and tracks which one is currently active.

    Loads agents from two sources (in priority order):
      1. Built-ins defined in _BUILTIN (shipped with the project)
      2. Plugin agents installed to ~/.amini/agents/<name>/ by AddonInstaller

    Each agent receives a FilteredToolRegistry (a view of the global ToolRegistry
    filtered to only the sub-agents equipped for that agent per config).

    Live-reload API
    ---------------
    enable_agent(slug)   — instantiate + add to cycling list immediately
    disable_agent(slug)  — call on_exit + remove from cycling list immediately
    update_equipped_sub_agents(slug, slugs) — rebuild FilteredToolRegistry for agent
    """

    def __init__(
        self,
        slugs: list[str],
        orchestrator: ModelOrchestrator,
        tool_registry: ToolRegistry,
        paths: "Optional[AmiPaths]" = None,
        context: "Optional[AgentContext]" = None,
        config_manager: "Optional[ConfigManager]" = None,
    ):
        self._orchestrator = orchestrator
        self._tool_registry = tool_registry
        self._paths = paths
        self._context = context
        self._config_manager = config_manager

        self._slugs = slugs
        self._index = 0
        self._instances: dict = {}
        self._filtered_registries: dict[str, FilteredToolRegistry] = {}

        for s in slugs:
            self._filtered_registries[s] = self._build_filtered_registry(s)
            self._instances[s] = self._load(s, orchestrator, self._filtered_registries[s])

    # ------------------------------------------------------------------
    # Public API — read
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
        # Ensure a filtered registry exists for injected agents too
        if slug not in self._filtered_registries:
            self._filtered_registries[slug] = self._build_filtered_registry(slug)

    def get_current_agent(self):
        return self._instances[self.current]

    # ------------------------------------------------------------------
    # Live-reload API
    # ------------------------------------------------------------------

    def enable_agent(self, slug: str) -> None:
        """
        Instantiate and add *slug* to the cycling list immediately.

        If already active, this is a no-op. Also updates config.
        """
        if slug in self._slugs:
            return  # already enabled
        self._filtered_registries[slug] = self._build_filtered_registry(slug)
        instance = self._load(slug, self._orchestrator, self._filtered_registries[slug])
        self._instances[slug] = instance
        self._slugs.append(slug)
        if self._config_manager:
            self._config_manager.set_agent_enabled(slug, True)
        logger.info("Agent '%s' enabled (live)", slug)

    def disable_agent(self, slug: str) -> None:
        """
        Remove *slug* from the cycling list immediately.

        If it is the current agent, cycle to the next one first.
        If only one agent remains, raises ValueError.
        """
        if slug not in self._slugs:
            return  # already disabled
        if len(self._slugs) <= 1:
            raise ValueError("Cannot disable the only active agent")

        if self.current == slug:
            self.cycle()
            # After cycle, re-adjust index to account for removal below
        agent = self._instances[slug]
        agent.on_exit(self._context)

        idx = self._slugs.index(slug)
        self._slugs.pop(idx)
        del self._instances[slug]
        # Fix up index if needed
        if self._index >= len(self._slugs):
            self._index = len(self._slugs) - 1

        if self._config_manager:
            self._config_manager.set_agent_enabled(slug, False)
        logger.info("Agent '%s' disabled (live)", slug)

    def update_equipped_sub_agents(self, slug: str, equipped_slugs: list[str]) -> None:
        """
        Rebuild the FilteredToolRegistry for *slug* with new equip list.

        Takes effect immediately on the next tool call — no agent restart needed.
        Also persists to config.
        """
        if slug in self._filtered_registries:
            self._filtered_registries[slug].update_allowed_slugs(set(equipped_slugs))
        else:
            fr = self._build_filtered_registry(slug, override_slugs=set(equipped_slugs))
            self._filtered_registries[slug] = fr

        if self._config_manager:
            self._config_manager.set_agent_equipped_sub_agents(slug, equipped_slugs)
        logger.info("Agent '%s' equipped sub-agents updated: %s", slug, equipped_slugs)

    # ------------------------------------------------------------------
    # Metadata (used by config API route)
    # ------------------------------------------------------------------

    def get_all_agent_metadata(self) -> list[dict]:
        """
        Return metadata for ALL known agents (built-in + installed add-ons),
        regardless of enabled state.

        Shape: [{slug, display_name, enabled, source,
                 equipped_sub_agents: [{slug, display_name, equipped}]}]
        """
        all_slugs: list[str] = []
        seen: set[str] = set()

        # Built-ins first
        for s in _BUILTIN:
            if s not in seen and s != "qa":  # skip compat alias
                all_slugs.append(s)
                seen.add(s)
        # ally (injected at runtime, not in _BUILTIN)
        if "ally" not in seen:
            all_slugs.append("ally")
            seen.add("ally")
        # Installed add-ons
        if self._paths:
            for s in self._paths.list_agents():
                if s not in seen:
                    all_slugs.append(s)
                    seen.add(s)

        all_sub_agents = self._tool_registry.list_sub_agents()
        result = []
        for slug in all_slugs:
            agent_cfg = (
                self._config_manager.get_agent_config(slug)
                if self._config_manager
                else {"enabled": slug in self._slugs, "equipped_sub_agents": []}
            )
            enabled = slug in self._slugs
            equipped_set = set(agent_cfg.get("equipped_sub_agents", []))

            sub_agent_list = [
                {
                    "slug": sa.slug,
                    "display_name": sa.display_name,
                    "equipped": sa.slug in equipped_set,
                }
                for sa in all_sub_agents
                if sa.slug  # skip sub-agents without a slug
            ]

            source = "addon" if (
                self._paths and self._paths.agent_dir(slug).exists()
                and slug not in _BUILTIN and slug != "ally"
            ) else "builtin"

            result.append({
                "slug": slug,
                "display_name": _BUILTIN_DISPLAY.get(slug, slug.replace("_", " ").title()),
                "enabled": enabled,
                "source": source,
                "sub_agents": sub_agent_list,
            })
        return result

    # ------------------------------------------------------------------
    # Agent loading
    # ------------------------------------------------------------------

    def _build_filtered_registry(
        self,
        slug: str,
        override_slugs: Optional[set] = None,
    ) -> FilteredToolRegistry:
        """Build a FilteredToolRegistry for *slug* based on config."""
        if override_slugs is not None:
            allowed = override_slugs
        elif self._config_manager:
            cfg = self._config_manager.get_agent_config(slug)
            allowed = set(cfg.get("equipped_sub_agents", []))
        else:
            # No config — allow all sub-agents (backward-compat)
            allowed = {sa.slug for sa in self._tool_registry.list_sub_agents() if sa.slug}
        return FilteredToolRegistry(self._tool_registry, allowed)

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
