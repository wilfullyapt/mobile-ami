"""
Family intercom message tool.

Voice messages are stored as text at ~/.amini/data/messages/<recipient>/inbox.json.
Each message: { "from": str, "text": str, "timestamp": str, "read": bool }

The LLM calls these tools to leave or read messages between family members.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from agents.tools.base_tool import BaseTool, ToolParam

logger = logging.getLogger(__name__)


class MessageLeaveTool(BaseTool):
    """Leave a voice message for a family member."""

    name = "message_leave"
    description = (
        "Leave a message for a specific family member. "
        "They will hear it the next time they interact with the assistant."
    )
    parameters = [
        ToolParam("recipient", "string", "Name of the family member to send the message to"),
        ToolParam("text", "string", "The message content"),
        ToolParam("sender", "string", "Name of the person leaving the message (optional)", required=False),
    ]

    def __init__(self, messages_dir: Path):
        self._messages_dir = messages_dir

    def execute(self, recipient: str, text: str, sender: str = "") -> str:
        inbox = _inbox_path(self._messages_dir, recipient)
        messages = _load(inbox)
        messages.append({
            "from": sender or "someone",
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "read": False,
        })
        _save(inbox, messages)
        logger.info("Message left for '%s' from '%s'", recipient, sender or "unknown")
        return f"Message left for {recipient}."


class MessageReadTool(BaseTool):
    """Read unread messages for a family member."""

    name = "message_read"
    description = (
        "Read any unread messages waiting for a specific family member."
    )
    parameters = [
        ToolParam("recipient", "string", "Name of the family member whose messages to read"),
    ]

    def __init__(self, messages_dir: Path):
        self._messages_dir = messages_dir

    def execute(self, recipient: str) -> str:
        inbox = _inbox_path(self._messages_dir, recipient)
        messages = _load(inbox)
        unread = [m for m in messages if not m["read"]]
        if not unread:
            return f"No new messages for {recipient}."

        # Mark all as read
        for m in messages:
            m["read"] = True
        _save(inbox, messages)

        parts = []
        for m in unread:
            sender = m.get("from", "someone")
            parts.append(f"Message from {sender}: {m['text']}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _inbox_path(messages_dir: Path, name: str) -> Path:
    return messages_dir / name.lower() / "inbox.json"


def _load(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save(path: Path, messages: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, indent=2))
