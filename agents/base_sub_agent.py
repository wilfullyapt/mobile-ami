"""
BaseSubAgent — bridges BaseTool and BaseAgent concepts.

A sub-agent is a BaseTool (so the LLM can call it via tool-calling)
that also carries an orchestrator reference and optional paths, and
may expose multiple related tools via get_additional_tools().

Usage
-----
class MySubAgent(BaseSubAgent):
    name = "my_primary_tool"
    description = "..."
    parameters = [...]

    def execute(self, **kwargs) -> str: ...

    def get_additional_tools(self) -> list[BaseTool]:
        return [MySecondaryTool()]

register_sub_agent(tool_registry, MySubAgent(orchestrator, paths))
"""
from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Optional

from agents.tools.base_tool import BaseTool
from agents.tools.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from core.models.orchestrator import ModelOrchestrator
    from core.ami_paths import AmiPaths


class BaseSubAgent(BaseTool, ABC):
    """
    Abstract sub-agent: a primary BaseTool that may expose additional tools.
    """

    def __init__(
        self,
        orchestrator: "ModelOrchestrator",
        paths: "Optional[AmiPaths]" = None,
    ):
        self._orchestrator = orchestrator
        self._paths = paths

    def get_additional_tools(self) -> list[BaseTool]:
        """
        Override to return extra tools this sub-agent provides beyond itself.
        All returned tools will be registered alongside the primary.
        """
        return []


def register_sub_agent(registry: ToolRegistry, sub: BaseSubAgent) -> None:
    """Register *sub* (primary) and all its additional tools into *registry*."""
    registry.register(sub)
    for tool in sub.get_additional_tools():
        registry.register(tool)
