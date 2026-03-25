"""
Soul management tools — private Ally tools for manipulating soul.md sections.

NOT registered in the global ToolRegistry. Only used inside AllyAgent's own
``_tool_loop`` so the LLM can inspect and reshape the soul document without
exposing soul-writing to any other agent.

Five tools are provided:

    soul_list_sections   — list current headings + levels in order
    soul_update_section  — replace (or create) a named section's content
    soul_add_section     — insert a new section at a specified position
    soul_remove_section  — delete a named section
    soul_reorder_sections — reorder sections by supplying the new heading order

All tools write soul.md atomically and record the change in soul_update.json
(via SoulManager._record_update) so the web UI can surface what changed.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from agents.tools.base_tool import BaseTool, ToolParam

if TYPE_CHECKING:
    from core.ally.soul import SoulManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# soul_list_sections
# ---------------------------------------------------------------------------

class SoulListSectionsTool(BaseTool):
    """Return the ordered list of section headings currently in soul.md."""

    name = "soul_list_sections"
    description = (
        "List all section headings currently in soul.md, in document order. "
        "Returns a JSON array of {heading, level} objects. "
        "Call this before making structural changes to understand the current layout."
    )
    parameters: list = []

    def __init__(self, soul_manager: "SoulManager"):
        self._soul = soul_manager

    def execute(self, **_kwargs) -> str:
        from core.ally.soul_section_manager import SoulSectionManager
        ssm = SoulSectionManager()
        sections = ssm.parse(self._soul.read())
        items = [
            {"heading": s.heading, "level": s.level}
            for s in sections
            if s.heading is not None
        ]
        return json.dumps(items, indent=2)


# ---------------------------------------------------------------------------
# soul_update_section
# ---------------------------------------------------------------------------

class SoulUpdateSectionTool(BaseTool):
    """Replace or create a named section in soul.md."""

    name = "soul_update_section"
    description = (
        "Update or create a named section in soul.md. "
        "Provide the section heading (without # markers) and the new content. "
        "If the section does not exist it is appended at the end."
    )
    parameters = [
        ToolParam("section", "string", "Section heading without # markers, e.g. 'Purpose'", required=True),
        ToolParam("content", "string", "New content for the section (plain text or markdown)", required=True),
    ]

    def __init__(self, soul_manager: "SoulManager"):
        self._soul = soul_manager

    def execute(self, section: str, content: str, **_kwargs) -> str:
        self._soul.update_section(section.strip(), content.strip())
        logger.info("SoulUpdateSectionTool: updated '%s'", section)
        return f"Updated soul section '{section}'."


# ---------------------------------------------------------------------------
# soul_add_section
# ---------------------------------------------------------------------------

class SoulAddSectionTool(BaseTool):
    """Insert a new section into soul.md at a specified position."""

    name = "soul_add_section"
    description = (
        "Add a new section to soul.md. "
        "Specify the heading, content, and optionally where to insert it. "
        "Use 'after' to place it after a named section, or 'position' (integer) "
        "to insert at a specific index. Defaults to appending at the end. "
        "Use 'level' (1–6) to set the heading depth (default 2 = ##)."
    )
    parameters = [
        ToolParam("section", "string", "New section heading (without # markers)", required=True),
        ToolParam("content", "string", "Section content (plain text or markdown)", required=True),
        ToolParam("level", "integer", "Heading level 1–6 (default 2)", required=False),
        ToolParam("after", "string", "Insert after this existing heading (optional)", required=False),
        ToolParam("position", "integer", "Insert at this index position (optional)", required=False),
    ]

    def __init__(self, soul_manager: "SoulManager"):
        self._soul = soul_manager

    def execute(
        self,
        section: str,
        content: str,
        level: int = 2,
        after: str | None = None,
        position: int | None = None,
        **_kwargs,
    ) -> str:
        self._soul.add_section(
            section.strip(),
            content.strip(),
            level=int(level),
            after=after.strip() if after else None,
            position=int(position) if position is not None else None,
        )
        logger.info("SoulAddSectionTool: added '%s'", section)
        return f"Added soul section '{section}'."


# ---------------------------------------------------------------------------
# soul_remove_section
# ---------------------------------------------------------------------------

class SoulRemoveSectionTool(BaseTool):
    """Delete a named section from soul.md."""

    name = "soul_remove_section"
    description = (
        "Remove a named section from soul.md. "
        "The section heading and all its content are deleted. "
        "No-op if the section does not exist."
    )
    parameters = [
        ToolParam("section", "string", "Section heading to remove (without # markers)", required=True),
    ]

    def __init__(self, soul_manager: "SoulManager"):
        self._soul = soul_manager

    def execute(self, section: str, **_kwargs) -> str:
        self._soul.remove_section(section.strip())
        logger.info("SoulRemoveSectionTool: removed '%s'", section)
        return f"Removed soul section '{section}'."


# ---------------------------------------------------------------------------
# soul_reorder_sections
# ---------------------------------------------------------------------------

class SoulReorderSectionsTool(BaseTool):
    """Reorder soul.md sections by supplying the new heading order."""

    name = "soul_reorder_sections"
    description = (
        "Reorder the sections of soul.md. "
        "Provide a JSON array of heading strings in the desired order. "
        "Sections not mentioned are appended at the end in their current relative order. "
        "Example: '[\"Identity\", \"Journal Entry Snapshot\", \"Purpose\"]'"
    )
    parameters = [
        ToolParam(
            "order",
            "string",
            "JSON array of heading strings in the desired order",
            required=True,
        ),
    ]

    def __init__(self, soul_manager: "SoulManager"):
        self._soul = soul_manager

    def execute(self, order: str, **_kwargs) -> str:
        try:
            new_order = json.loads(order)
            if not isinstance(new_order, list):
                return "Error: 'order' must be a JSON array of strings."
        except json.JSONDecodeError as exc:
            return f"Error parsing order JSON: {exc}"

        self._soul.reorder_sections([str(h) for h in new_order])
        logger.info("SoulReorderSectionsTool: reordered %d sections", len(new_order))
        return f"Reordered soul sections: {new_order}."
