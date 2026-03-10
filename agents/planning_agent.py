"""
PlanningAgent — multi-step reasoning agent.

Breaks goals into numbered steps and calls tools for each step.
Exposes the full ToolRegistry surface to the LLM (not just get_tools())
so it can delegate to any registered sub-agent.

Stores the most recent plan in context.agent_memory("planning")["last_plan"].
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from agents.base_agent import BaseAgent
from core.model_registry import ModelRole

if TYPE_CHECKING:
    from core.agent_context import AgentContext

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 10

_SYSTEM_PROMPT = (
    "You are a methodical planning assistant. "
    "When given a goal, break it into numbered steps and execute each step "
    "using the available tools. Think carefully before each tool call. "
    "Summarise what you accomplished at the end."
)


class PlanningAgent(BaseAgent):
    """
    Multi-step planning agent with access to the full tool surface.

    Unlike QAAgent (which only sees its own get_tools()), PlanningAgent
    calls self._tool_registry.all_schemas() so it can use every registered
    tool including all sub-agent tools.
    """

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def on_entry(self, context: "AgentContext") -> None:
        context.set_flag("active_agent", "planning")

    def on_exit(self, context: "AgentContext") -> None:
        pass

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def process(
        self,
        text: str,
        speaker: Optional[str] = None,
        context: "Optional[AgentContext]" = None,
    ) -> str:
        llm = self._orchestrator.get(ModelRole.LLM)
        # Give the LLM the full tool surface from the shared registry
        tools = self._tool_registry.all_schemas()

        effective_speaker = (
            (context.current_speaker if context else None)
            or speaker
        )

        messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]

        if effective_speaker:
            messages.append({
                "role": "system",
                "content": f"You are helping {effective_speaker}.",
            })

        if context:
            messages.extend(context.recent_history(10))

        messages.append({"role": "user", "content": text})

        for _ in range(_MAX_TOOL_ROUNDS):
            response, tool_calls = llm.chat_with_tools(messages, tools or None)

            if not tool_calls:
                final = response or "I was unable to complete the plan."
                if context:
                    context.agent_memory("planning")["last_plan"] = final
                    context.add_message("assistant", final)
                return final

            messages.append({
                "role": "assistant",
                "content": response,
                "tool_calls": tool_calls,
            })
            for call in tool_calls:
                result = self._tool_registry.execute(call["name"], call["args"])
                logger.info("Tool %s → %s", call["name"], result)
                messages.append({"role": "tool", "content": result, "name": call["name"]})

        final = llm.chat(messages)
        if context:
            context.agent_memory("planning")["last_plan"] = final
            if final:
                context.add_message("assistant", final)
        return final or "Plan completed."
