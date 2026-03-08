"""
Calendar tool — read and write a shared family calendar.

Events are stored as a JSON list at ~/.amini/data/calendar.json.
Each event has: title, date (YYYY-MM-DD), time (HH:MM, optional),
person (whose event it is, optional), and notes (optional).

The LLM calls this tool to add or query events.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from agents.tools.base_tool import BaseTool, ToolParam

logger = logging.getLogger(__name__)


class CalendarAddTool(BaseTool):
    """Add an event to the shared family calendar."""

    name = "calendar_add"
    description = (
        "Add an event to the family calendar. "
        "Use this when someone wants to schedule something."
    )
    parameters = [
        ToolParam("title", "string", "Brief title for the event, e.g. 'Soccer practice'"),
        ToolParam("date", "string", "Date in YYYY-MM-DD format"),
        ToolParam("time", "string", "Time in HH:MM 24-hour format (optional)", required=False),
        ToolParam("person", "string", "Family member this event belongs to (optional)", required=False),
        ToolParam("notes", "string", "Any additional notes (optional)", required=False),
    ]

    def __init__(self, calendar_path: Path):
        self._path = calendar_path

    def execute(self, title: str, date: str, time: str = "", person: str = "", notes: str = "") -> str:
        events = _load(self._path)
        event = {"title": title, "date": date, "time": time, "person": person, "notes": notes}
        events.append(event)
        _save(self._path, events)
        who = f" for {person}" if person else ""
        at = f" at {time}" if time else ""
        logger.info("Calendar: added '%s'%s on %s%s", title, who, date, at)
        return f"Added '{title}'{who} on {date}{at}."


class CalendarQueryTool(BaseTool):
    """Query upcoming events from the shared family calendar."""

    name = "calendar_query"
    description = (
        "Look up events on the family calendar. "
        "Use this to answer questions about what is scheduled."
    )
    parameters = [
        ToolParam("date_from", "string", "Start date to search from (YYYY-MM-DD)", required=False),
        ToolParam("date_to", "string", "End date to search to (YYYY-MM-DD)", required=False),
        ToolParam("person", "string", "Filter by family member name (optional)", required=False),
    ]

    def __init__(self, calendar_path: Path):
        self._path = calendar_path

    def execute(self, date_from: str = "", date_to: str = "", person: str = "") -> str:
        events = _load(self._path)
        if not events:
            return "The family calendar is empty."

        filtered = events
        if date_from:
            filtered = [e for e in filtered if e.get("date", "") >= date_from]
        if date_to:
            filtered = [e for e in filtered if e.get("date", "") <= date_to]
        if person:
            filtered = [
                e for e in filtered
                if not e.get("person") or e["person"].lower() == person.lower()
            ]

        if not filtered:
            return "No events found for that period."

        filtered.sort(key=lambda e: (e.get("date", ""), e.get("time", "")))
        lines = []
        for e in filtered[:10]:  # cap spoken list at 10 items
            who = f" ({e['person']})" if e.get("person") else ""
            at = f" at {e['time']}" if e.get("time") else ""
            lines.append(f"{e['date']}{at}: {e['title']}{who}")
        return ". ".join(lines) + "."


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save(path: Path, events: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(events, indent=2))
