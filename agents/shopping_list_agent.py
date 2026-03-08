"""
ShoppingListAgent — manage the shared family shopping list.

Understands natural language like:
    "Add milk and eggs to the list"
    "What do we need from the shop?"
    "I picked up the bread, mark it done"

Items are stored locally at ~/.amini/data/shopping_list.json.
The agent tracks who added each item so you can say "Dad already added bread".
"""

import logging
from typing import Optional

from agents.base_agent import BaseAgent
from agents.tools.shopping_tool import ShoppingAddTool, ShoppingQueryTool, ShoppingDoneTool
from core.model_registry import ModelRole

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a helpful family shopping list assistant.
{speaker_line}
You manage the household shopping list. Use the tools to add items, read the
list, or mark items as purchased. Keep responses short — this is a voice
interface. When someone adds items, confirm what was added. When reading the
list, read it out naturally.
"""


class ShoppingListAgent(BaseAgent):
    """
    Shared family shopping list agent.

    Exposes three tools: shopping_add, shopping_query, shopping_done.
    """

    def get_tools(self):
        if self._paths is None:
            return []
        list_path = self._paths.data_dir / "shopping_list.json"
        return [
            ShoppingAddTool(list_path),
            ShoppingQueryTool(list_path),
            ShoppingDoneTool(list_path),
        ]

    def process(self, text: str, speaker: Optional[str] = None) -> str:
        llm = self._orchestrator.get(ModelRole.LLM)
        tools = [t.to_llm_schema() for t in self.get_tools()]

        speaker_line = f"The person speaking is {speaker}." if speaker else ""
        system = _SYSTEM_PROMPT.format(speaker_line=speaker_line)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]

        response, tool_calls = llm.chat_with_tools(messages, tools or None)

        if tool_calls:
            results = []
            for call in tool_calls:
                result = self._tool_registry.execute(call["name"], call["args"])
                logger.info("Tool %s → %s", call["name"], result)
                results.append(result)
            return " ".join(results)

        return response or "I couldn't understand that shopping request."
