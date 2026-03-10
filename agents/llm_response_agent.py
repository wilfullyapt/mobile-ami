"""
LLMResponseAgent — context-aware general-purpose Q&A agent.

Drop-in replacement for QAAgent that seeds conversation history from
the shared AgentContext and appends responses back to it.

``_BUILTIN["qa"]`` points here for backward compatibility; qa_agent.py
is preserved so any direct imports keep working.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from agents.base_agent import BaseAgent
from core.model_registry import ModelRole

if TYPE_CHECKING:
    from core.agent_context import AgentContext

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 5


class LLMResponseAgent(BaseAgent):
    """
    General-purpose Q&A backed by the LLM with optional context awareness.

    When an AgentContext is provided, the last 10 messages of conversation
    history are used to seed the prompt (giving the LLM short-term memory),
    and both the user turn and assistant reply are appended back to the
    shared context so all agents see a consistent history.
    """

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def on_entry(self, context: "AgentContext") -> None:
        context.set_flag("active_agent", "llm_response")

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
        tools = [t.to_llm_schema() for t in self.get_tools()]

        # Determine effective speaker name
        effective_speaker = (
            (context.current_speaker if context else None)
            or speaker
        )

        messages: list[dict] = []

        if effective_speaker:
            messages.append({
                "role": "system",
                "content": (
                    "You are a friendly family AI assistant. "
                    f"The person speaking is {effective_speaker}. "
                    "Address them by name when natural."
                ),
            })

        # Seed from shared history when context is available
        if context:
            messages.extend(context.recent_history(10))

        messages.append({"role": "user", "content": text})

        for _ in range(_MAX_TOOL_ROUNDS):
            response, tool_calls = llm.chat_with_tools(messages, tools or None)

            if not tool_calls:
                final = response or "I'm not sure how to answer that."
                if context:
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

        # Fallback: get a final answer without tools
        final = llm.chat(messages)
        if context and final:
            context.add_message("assistant", final)
        return final
