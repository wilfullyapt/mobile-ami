from __future__ import annotations

from typing import TYPE_CHECKING

from agents.tools.base_tool import BaseTool

if TYPE_CHECKING:
    from agents.base_sub_agent import BaseSubAgent


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._sub_agents: dict[str, "BaseSubAgent"] = {}   # slug → sub-agent instance

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def register_sub_agent_meta(self, sub_agent: "BaseSubAgent") -> None:
        """Index *sub_agent* by slug so the server can enumerate sub-agents."""
        from agents.base_sub_agent import BaseSubAgent as _Base  # avoid circular at module load
        if isinstance(sub_agent, _Base) and sub_agent.slug:
            self._sub_agents[sub_agent.slug] = sub_agent

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(f"No tool registered with name: {name!r}")
        return self._tools[name]

    def all_schemas(self) -> list[dict]:
        """Return Ollama-compatible schema list for all registered tools."""
        return [t.to_llm_schema() for t in self._tools.values()]

    def execute(self, name: str, args: dict) -> str:
        """Look up and execute a tool by name, returning its string result."""
        tool = self.get(name)
        return tool.execute(**args)

    # ------------------------------------------------------------------
    # Sub-agent enumeration (used by config API)
    # ------------------------------------------------------------------

    def list_sub_agents(self) -> list["BaseSubAgent"]:
        """All registered sub-agents (one per unique slug)."""
        return list(self._sub_agents.values())

    def get_sub_agent(self, slug: str) -> "BaseSubAgent | None":
        return self._sub_agents.get(slug)


class FilteredToolRegistry(ToolRegistry):
    """
    Read-only proxy over a parent ToolRegistry that only exposes tools
    whose sub-agent slug is in *allowed_slugs*.

    Tools whose sub-agent slug is unknown (e.g. legacy tools not registered
    as sub-agents) are always exposed — this preserves backward compat.
    """

    def __init__(self, parent: ToolRegistry, allowed_slugs: set[str]):
        # Do NOT call super().__init__() — we delegate to parent
        self._parent = parent
        self._allowed_slugs = set(allowed_slugs)
        # Build the set of tool names that are allowed
        self._rebuild()

    def update_allowed_slugs(self, allowed_slugs: set[str]) -> None:
        """Update the filter in-place; takes effect on the next tool call."""
        self._allowed_slugs = set(allowed_slugs)
        self._rebuild()

    def _rebuild(self) -> None:
        """Recompute which tool names pass the filter."""
        # Build reverse map: tool_name → sub_agent_slug
        slug_by_tool: dict[str, str] = {}
        for slug, sa in self._parent._sub_agents.items():
            slug_by_tool[sa.name] = slug
            for extra in sa.get_additional_tools():
                slug_by_tool[extra.name] = slug

        self._allowed_tool_names: set[str] = set()
        for tool_name in self._parent._tools:
            tool_slug = slug_by_tool.get(tool_name)
            if tool_slug is None:
                # Tool not associated with any sub-agent — always pass
                self._allowed_tool_names.add(tool_name)
            elif tool_slug in self._allowed_slugs:
                self._allowed_tool_names.add(tool_name)

    def register(self, tool: BaseTool):  # type: ignore[override]
        raise RuntimeError("FilteredToolRegistry is read-only; register on the parent")

    def get(self, name: str) -> BaseTool:
        # Allow get() even for filtered-out tools so execute() can still work
        # (agent may call tools directly if it knows the name)
        return self._parent.get(name)

    def all_schemas(self) -> list[dict]:
        return [
            t.to_llm_schema()
            for name, t in self._parent._tools.items()
            if name in self._allowed_tool_names
        ]

    def execute(self, name: str, args: dict) -> str:
        return self._parent.execute(name, args)

    def list_sub_agents(self) -> list["BaseSubAgent"]:
        return self._parent.list_sub_agents()

    def get_sub_agent(self, slug: str) -> "BaseSubAgent | None":
        return self._parent.get_sub_agent(slug)
