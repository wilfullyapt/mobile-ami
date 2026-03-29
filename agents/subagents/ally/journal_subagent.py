"""
Journal tools — private Ally tools for reading and writing daily journal entries.

NOT registered in the global ToolRegistry. Only used inside AllyAgent's own
``_tool_loop`` and EvalDay's journal session so the LLM can write and later
read its own daily record.

Three tools are provided:

    journal_write    — persist today's journal entry (structured metadata + prose)
    journal_read     — retrieve one or more entries (full text including summary)
    journal_summary  — return metadata for the last N entries (no prose)
                       for use as input to a journal snapshot rewrite

``journal_summary`` is a data tool — it returns formatted metadata text.
The LLM (in EvalDay's tool loop) reads that text and writes the compressed
snapshot narrative itself, then calls ``soul_update_section`` to persist it.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from agents.tools.base_tool import BaseTool, ToolParam
from core.ally.journal_manager import JournalEntry

if TYPE_CHECKING:
    from core.ally.journal_manager import JournalManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# journal_write
# ---------------------------------------------------------------------------

class JournalWriteTool(BaseTool):
    """Write today's journal entry to disk."""

    name = "journal_write"
    description = (
        "Write a daily journal entry. Provide the date, a prose narrative summary, "
        "and structured metadata fields (topics, key_events, emotional_tone, action_items). "
        "This is called once per daily review session to persist the day's reflection."
    )
    parameters = [
        ToolParam("date", "string", "ISO date YYYY-MM-DD for this entry", required=True),
        ToolParam("summary", "string", "Prose narrative of the day (your personal reflection)", required=True),
        ToolParam("topics", "string", "JSON array of topic strings, e.g. '[\"work\", \"family\"]'", required=False),
        ToolParam("key_events", "string", "JSON array of notable event strings", required=False),
        ToolParam("emotional_tone", "string", "Overall emotional tone, e.g. 'contemplative'", required=False),
        ToolParam("action_items", "string", "JSON array of follow-up action strings", required=False),
    ]

    def __init__(self, journal_manager: "JournalManager"):
        self._journal = journal_manager

    def execute(
        self,
        date: str,
        summary: str,
        topics: str = "[]",
        key_events: str = "[]",
        emotional_tone: str = "",
        action_items: str = "[]",
        **_kwargs,
    ) -> str:
        try:
            topics_list = json.loads(topics) if topics else []
        except json.JSONDecodeError:
            topics_list = [topics] if topics else []
        try:
            events_list = json.loads(key_events) if key_events else []
        except json.JSONDecodeError:
            events_list = [key_events] if key_events else []
        try:
            actions_list = json.loads(action_items) if action_items else []
        except json.JSONDecodeError:
            actions_list = [action_items] if action_items else []

        entry = JournalEntry(
            date=date.strip(),
            summary=summary.strip(),
            topics=topics_list,
            key_events=events_list,
            emotional_tone=emotional_tone.strip(),
            action_items=actions_list,
        )
        self._journal.write(entry)
        logger.info("JournalWriteTool: wrote entry for %s", date)
        return f"Journal entry written for {date}."


# ---------------------------------------------------------------------------
# journal_read
# ---------------------------------------------------------------------------

class JournalReadTool(BaseTool):
    """Read one or more journal entries."""

    name = "journal_read"
    description = (
        "Read journal entries. Provide one of: "
        "'date' for a single entry (YYYY-MM-DD), "
        "'start_date' + 'end_date' for a date range, "
        "or 'last_n' (integer) for the most recent N entries. "
        "Returns full entries including the prose summary."
    )
    parameters = [
        ToolParam("date", "string", "Single ISO date YYYY-MM-DD (optional)", required=False),
        ToolParam("start_date", "string", "Range start ISO date (optional)", required=False),
        ToolParam("end_date", "string", "Range end ISO date (optional)", required=False),
        ToolParam("last_n", "integer", "Number of most recent entries to return (optional)", required=False),
    ]

    def __init__(self, journal_manager: "JournalManager"):
        self._journal = journal_manager

    def execute(
        self,
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        last_n: int | None = None,
        **_kwargs,
    ) -> str:
        if date:
            entry = self._journal.read_date(date.strip())
            if entry is None:
                return f"No journal entry found for {date}."
            return self._format_entries([entry])

        if start_date and end_date:
            entries = self._journal.read_range(start_date.strip(), end_date.strip())
            if not entries:
                return f"No journal entries found between {start_date} and {end_date}."
            return self._format_entries(entries)

        if last_n is not None:
            entries = self._journal.read_last_n(int(last_n))
            if not entries:
                return "No journal entries found."
            return self._format_entries(entries)

        return "Provide 'date', 'start_date'+'end_date', or 'last_n' to read journal entries."

    @staticmethod
    def _format_entries(entries: list) -> str:
        parts = []
        for e in entries:
            parts.append(
                f"=== {e.date} ===\n"
                f"Topics: {', '.join(e.topics) or '(none)'}\n"
                f"Emotional tone: {e.emotional_tone or '(none)'}\n"
                f"Key events: {'; '.join(e.key_events) or '(none)'}\n"
                f"Action items: {'; '.join(e.action_items) or '(none)'}\n"
                f"\n{e.summary}"
            )
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# journal_summary
# ---------------------------------------------------------------------------

class JournalSummaryTool(BaseTool):
    """
    Return structured metadata for the last N journal entries (no prose).

    This is a data tool — it formats metadata as human-readable text for the
    LLM to read and compress into a snapshot narrative. The LLM then writes
    the narrative via soul_update_section. No LLM call happens inside this tool.
    """

    name = "journal_summary"
    description = (
        "Return structured metadata for the last N journal entries, without full summaries. "
        "Used to build a compressed 'Journal Entry Snapshot' for the soul. "
        "The returned text contains dates, topics, key events, and emotional tones "
        "across the requested period — ready for you to synthesise into a snapshot narrative."
    )
    parameters = [
        ToolParam("last_n", "integer", "Number of recent entries to scan (default 100)", required=False),
    ]

    def __init__(self, journal_manager: "JournalManager"):
        self._journal = journal_manager

    def execute(self, last_n: int = 100, **_kwargs) -> str:
        meta_list = self._journal.read_metadata_last_n(int(last_n))
        if not meta_list:
            return "No journal entries found. Cannot generate summary."

        lines = [f"Journal metadata — last {len(meta_list)} entries (newest first):\n"]
        for m in meta_list:
            topics = ", ".join(m.get("topics", [])) or "(none)"
            tone = m.get("emotional_tone", "") or "(none)"
            events = "; ".join(m.get("key_events", [])) or "(none)"
            actions = "; ".join(m.get("action_items", [])) or "(none)"
            lines.append(
                f"[{m.get('date', '?')}] topics={topics} | tone={tone}\n"
                f"  events: {events}\n"
                f"  actions: {actions}"
            )

        return "\n".join(lines)
