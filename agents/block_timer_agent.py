import logging
from typing import Optional

from agents.base_agent import BaseAgent
from agents.tools.timer_tool import TimerTool
from core.model_registry import ModelRole

logger = logging.getLogger(__name__)


class BlockTimerAgent(BaseAgent):
    """
    Focus-timer agent.

    Uses the LLM to parse timer intent from natural language, then delegates
    execution to TimerTool. The LLM handles phrase parsing (e.g. "start a
    half-hour block") so the agent doesn't need hand-written regex.
    """

    def get_tools(self):
        tts = self._orchestrator.get(ModelRole.TTS)
        return [TimerTool(on_speak=tts.speak)]

    def process(self, text: str, speaker: Optional[str] = None) -> str:
        llm = self._orchestrator.get(ModelRole.LLM)
        tools = [t.to_llm_schema() for t in self.get_tools()]
        messages = [{"role": "user", "content": text}]

        response, tool_calls = llm.chat_with_tools(messages, tools)

        if tool_calls:
            for call in tool_calls:
                result = self._tool_registry.execute(call["name"], call["args"])
                logger.info("Tool %s → %s", call["name"], result)
            return result  # last tool result is the spoken confirmation

        # LLM chose not to call a tool — fall back to its text reply
        return response or "Timer command not recognized."
