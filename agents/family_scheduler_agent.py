"""
FamilySchedulerAgent — manage the shared family calendar.

Understands natural language like:
    "What's on this weekend?"
    "Add Jake's soccer practice Saturday at 3pm"
    "Do I have anything on Tuesday?"

Events are stored locally at ~/.amini/data/calendar.json.
When a speaker is identified, queries can be filtered to their events.
"""

import logging
from datetime import date
from typing import Optional

from agents.base_agent import BaseAgent
from agents.tools.calendar_tool import CalendarAddTool, CalendarQueryTool
from core.model_registry import ModelRole

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a family calendar assistant. Today's date is {today}.
{speaker_line}
You help manage the family's shared schedule. Use the calendar tools to add or
query events. When adding events, always confirm back what was scheduled.
When querying, read out the events in a natural, conversational way.
Keep responses brief — this is a voice interface.
"""


class FamilySchedulerAgent(BaseAgent):
    """
    Shared family calendar agent.

    Exposes two tools to the LLM: calendar_add and calendar_query.
    The LLM decides which to call based on the user's utterance.
    """

    def get_tools(self):
        if self._paths is None:
            return []
        calendar_path = self._paths.data_dir / "calendar.json"
        return [
            CalendarAddTool(calendar_path),
            CalendarQueryTool(calendar_path),
        ]

    def process(self, text: str, speaker: Optional[str] = None, context=None) -> str:
        llm = self._orchestrator.get(ModelRole.LLM)
        tools = [t.to_llm_schema() for t in self.get_tools()]

        speaker_line = f"The person speaking is {speaker}." if speaker else ""
        system = _SYSTEM_PROMPT.format(today=date.today().isoformat(), speaker_line=speaker_line)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]

        response, tool_calls = llm.chat_with_tools(messages, tools or None)

        if tool_calls:
            for call in tool_calls:
                result = self._tool_registry.execute(call["name"], call["args"])
                logger.info("Tool %s → %s", call["name"], result)
            return result

        return response or "I couldn't understand that calendar request."
