from agents.tools.base_tool import BaseTool


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

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
