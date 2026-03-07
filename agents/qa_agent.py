import logging

from agents.base_agent import BaseAgent
from core.model_registry import ModelRole

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 5  # guard against runaway tool-calling loops


class QAAgent(BaseAgent):
    """
    General-purpose Q&A agent backed by the LLM.

    Supports tool calling: the LLM can invoke any tool returned by get_tools().
    The agentic loop continues until the model stops requesting tool calls or
    the round limit is hit.
    """

    def process(self, text: str) -> str:
        llm = self._orchestrator.get(ModelRole.LLM)
        tools = [t.to_llm_schema() for t in self.get_tools()]
        messages = [{"role": "user", "content": text}]

        for _ in range(_MAX_TOOL_ROUNDS):
            response, tool_calls = llm.chat_with_tools(messages, tools or None)

            if not tool_calls:
                return response or "I'm not sure how to answer that."

            # Execute each tool call and fold results back into the conversation
            messages.append({"role": "assistant", "content": response, "tool_calls": tool_calls})
            for call in tool_calls:
                result = self._tool_registry.execute(call["name"], call["args"])
                logger.info("Tool %s → %s", call["name"], result)
                messages.append({"role": "tool", "content": result, "name": call["name"]})

        # Fallback: get a final answer without tools
        return llm.chat(messages)
