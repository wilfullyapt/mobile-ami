"""
ConversationSubAgent — conversation history access and summarisation.

Primary tool:    get_conversation_history(last_n=10)
Additional tool: summarize_conversation()

This is the only sub-agent that holds a direct reference to AgentContext.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from agents.base_sub_agent import BaseSubAgent
from agents.tools.base_tool import BaseTool, ToolParam

if TYPE_CHECKING:
    from core.models.orchestrator import ModelOrchestrator
    from core.ami_paths import AmiPaths
    from core.agent_context import AgentContext

logger = logging.getLogger(__name__)


class _SummarizeConversationTool(BaseTool):
    name = "summarize_conversation"
    description = "Generate a 2–3 sentence summary of the recent conversation."
    parameters = []

    def __init__(self, orchestrator, context: "Optional[AgentContext]"):
        self._orchestrator = orchestrator
        self._context = context

    def execute(self) -> str:
        if self._context is None:
            return "No conversation context available."
        from core.models.registry import ModelRole
        history = self._context.recent_history(20)
        if not history:
            return "No conversation history to summarise."
        messages = [
            {
                "role": "system",
                "content": "Summarise the following conversation in 2–3 sentences.",
            }
        ] + history
        try:
            llm = self._orchestrator.get(ModelRole.LLM)
            return llm.chat(messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning("summarize_conversation failed: %s", exc)
            return "Could not generate summary."


class ConversationSubAgent(BaseSubAgent):
    """Provides access to shared AgentContext conversation history."""

    slug = "conversation"
    display_name = "Conversation History"
    name = "get_conversation_history"
    description = "Retrieve recent conversation history as a formatted string."
    parameters = [
        ToolParam(
            "last_n",
            "integer",
            "Number of most recent messages to return (default 10)",
            required=False,
        ),
    ]

    def __init__(
        self,
        orchestrator: "ModelOrchestrator",
        paths: "Optional[AmiPaths]" = None,
        context: "Optional[AgentContext]" = None,
    ):
        super().__init__(orchestrator, paths)
        self._context = context

    def execute(self, last_n: int = 10) -> str:
        if self._context is None:
            return "No conversation context available."
        history = self._context.recent_history(last_n)
        if not history:
            return "No conversation history yet."
        lines = []
        for msg in history:
            role = msg.get("role", "unknown").capitalize()
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def get_additional_tools(self) -> list[BaseTool]:
        return [_SummarizeConversationTool(self._orchestrator, self._context)]
