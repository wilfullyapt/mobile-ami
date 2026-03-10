"""
FamilyIntercomAgent — leave and receive voice messages between family members.

Acts as an asynchronous household intercom: any family member can leave a
text message for another that will be read out the next time that person
interacts with the device.

Example interactions:
    "Leave a message for Mom: dinner is in the fridge"
    "Any messages for Jake?"
    "Do I have any messages?"   ← uses identified speaker automatically
    "Tell Dad I'll be home late"

Messages are stored at ~/.amini/data/messages/<recipient>/inbox.json.
"""

import logging
from typing import Optional

from agents.base_agent import BaseAgent
from agents.tools.message_tool import MessageLeaveTool, MessageReadTool
from core.model_registry import ModelRole

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a family intercom assistant on an AI voice device.
{speaker_line}
Use the tools to leave messages for family members or read out any unread
messages. When leaving a message, always include who it is from.
When reading messages, read them out naturally.
Keep responses brief — this is a voice interface.
"""


class FamilyIntercomAgent(BaseAgent):
    """
    Household voice message intercom.

    The LLM decides whether to call message_leave or message_read based on
    the user's utterance. If a speaker is identified, the sender name is
    automatically available so messages are attributed correctly.
    """

    def get_tools(self):
        if self._paths is None:
            return []
        messages_dir = self._paths.data_dir / "messages"
        return [
            MessageLeaveTool(messages_dir),
            MessageReadTool(messages_dir),
        ]

    def process(self, text: str, speaker: Optional[str] = None, context=None) -> str:
        llm = self._orchestrator.get(ModelRole.LLM)
        tools = [t.to_llm_schema() for t in self.get_tools()]

        speaker_line = (
            f"The person speaking is {speaker}. "
            "When leaving a message, use their name as the sender automatically."
            if speaker else ""
        )
        system = _SYSTEM_PROMPT.format(speaker_line=speaker_line)

        # If the user says "do I have any messages?" and we know who they are,
        # rewrite the query to be explicit so the LLM can call message_read correctly.
        if speaker and any(
            phrase in text.lower()
            for phrase in ("my messages", "any messages for me", "messages for me", "do i have")
        ):
            text = f"Read messages for {speaker}"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]

        response, tool_calls = llm.chat_with_tools(messages, tools or None)

        if tool_calls:
            results = []
            for call in tool_calls:
                # Auto-inject sender name if leaving a message and speaker is known
                if call["name"] == "message_leave" and speaker and not call["args"].get("sender"):
                    call["args"]["sender"] = speaker
                result = self._tool_registry.execute(call["name"], call["args"])
                logger.info("Tool %s → %s", call["name"], result)
                results.append(result)
            return " ".join(results)

        return response or "I couldn't understand that message request."
