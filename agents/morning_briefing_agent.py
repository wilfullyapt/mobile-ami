"""
MorningBriefingAgent — personalised morning briefing for each family member.

Greets the identified speaker by name and reads out a summary of:
  - Today's date and day of the week
  - Their calendar events for today (from ~/.amini/data/calendar.json)
  - Any unread messages waiting for them (from ~/.amini/data/messages/)
  - Shared household reminders

Example interactions:
    "Good morning"
    "What's my day looking like?"
    "Any messages for me?"
    "What's on the family schedule today?"

The agent is deliberately concise — it reads a useful morning snapshot in
under 30 seconds of spoken audio.
"""

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from agents.base_agent import BaseAgent
from core.models.registry import ModelRole

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a warm, concise morning briefing assistant for a family AI device.
Today is {today} ({weekday}).
{speaker_line}

Summarise the information below into a friendly spoken briefing (under 60 words).
Start with a personalised greeting. Mention today's events if any, then messages.
If there is nothing scheduled, say so encouragingly.
Keep it conversational — this will be read aloud.

=== Today's calendar events ===
{events}

=== Unread messages ===
{messages}
"""


class MorningBriefingAgent(BaseAgent):
    """
    Personalised morning briefing agent.

    Reads today's calendar events for the identified speaker and their unread
    messages, then uses the LLM to compose a natural spoken summary.
    """

    def on_entry(self, context=None) -> None:
        if context is not None:
            context.set_flag("active_agent", "morning_briefing")

    def on_exit(self, context=None) -> None:
        pass

    def process(self, text: str, speaker: Optional[str] = None, context=None) -> str:
        llm = self._orchestrator.get(ModelRole.LLM)

        today = date.today()
        events_text = self._get_todays_events(today, speaker)
        messages_text = self._get_unread_messages(speaker)

        speaker_line = (
            f"The person speaking is {speaker}. Address them by name in the greeting."
            if speaker else ""
        )

        system = _SYSTEM_PROMPT.format(
            today=today.isoformat(),
            weekday=today.strftime("%A"),
            speaker_line=speaker_line,
            events=events_text or "No events today.",
            messages=messages_text or "No unread messages.",
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]

        response = llm.chat(messages)
        return response or self._fallback_briefing(speaker, today)

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _get_todays_events(self, today: date, speaker: Optional[str]) -> str:
        if self._paths is None:
            return ""
        calendar_path = self._paths.data_dir / "calendar.json"
        if not calendar_path.exists():
            return ""
        try:
            events = json.loads(calendar_path.read_text())
        except (json.JSONDecodeError, OSError):
            return ""

        today_str = today.isoformat()
        todays = [
            e for e in events
            if e.get("date") == today_str
            and (not e.get("person") or not speaker or e["person"].lower() == speaker.lower())
        ]
        if not todays:
            return ""
        lines = []
        for e in todays:
            at = f" at {e['time']}" if e.get("time") else ""
            who = f" ({e['person']})" if e.get("person") and not speaker else ""
            lines.append(f"- {e['title']}{at}{who}")
        return "\n".join(lines)

    def _get_unread_messages(self, speaker: Optional[str]) -> str:
        if self._paths is None or not speaker:
            return ""
        inbox_path = self._paths.data_dir / "messages" / speaker.lower() / "inbox.json"
        if not inbox_path.exists():
            return ""
        try:
            msgs = json.loads(inbox_path.read_text())
        except (json.JSONDecodeError, OSError):
            return ""
        unread = [m for m in msgs if not m.get("read")]
        if not unread:
            return ""
        lines = [f"- From {m.get('from', 'someone')}: {m['text']}" for m in unread]
        return "\n".join(lines)

    def _fallback_briefing(self, speaker: Optional[str], today: date) -> str:
        name = f", {speaker}" if speaker else ""
        return (
            f"Good morning{name}! Today is {today.strftime('%A, %B %d')}. "
            "Have a wonderful day!"
        )
