"""
SoulUpdateSubAgent — internal ally tool to update a section of soul.md.

NOT registered in the global ToolRegistry. Only used inside AllyAgent's
own ``_tool_loop`` so the LLM can rewrite specific soul sections without
wiping the entire file (``create_for_owner`` is destructive and not called
from here).

Tool name: ``update_soul_section``
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agents.tools.base_tool import BaseTool, ToolParam

if TYPE_CHECKING:
    from core.models.orchestrator import ModelOrchestrator
    from core.ally.soul import SoulManager

logger = logging.getLogger(__name__)


class SoulUpdateSubAgent(BaseTool):
    """Replace or append a named ``## Section`` block in soul.md."""

    name = "update_soul_section"
    description = (
        "Update or add a named section in soul.md. "
        "Provide the section heading (without ##) and the new content."
    )
    parameters = [
        ToolParam("section", "string", "Section heading (without ##, e.g. 'Purpose')", required=True),
        ToolParam("content", "string", "New content for the section (plain text)", required=True),
    ]

    def __init__(self, orchestrator: "ModelOrchestrator", soul_manager: "SoulManager"):
        self._orch = orchestrator
        self._soul = soul_manager

    def execute(self, section: str, content: str) -> str:
        current = self._soul.read(has_owner=True)
        updated = self._replace_section(current, section.strip(), content.strip())
        self._soul.write_raw(updated)
        logger.info("SoulUpdateSubAgent: updated section '## %s'", section)
        return f"Updated soul section '## {section}'."

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _replace_section(text: str, section: str, new_content: str) -> str:
        """
        Find ``## {section}`` in *text*, replace its content until the next
        ``##`` heading (or EOF), and return the updated text.

        If the section is not found, append it.
        """
        heading = f"## {section}"
        # Split on any top-level heading (## ) boundary
        parts = text.split("\n## ")
        # parts[0] is everything before the first "## "
        # parts[1:] are "<heading>\n<body>" for each subsequent section

        for i, part in enumerate(parts):
            # Reconstruct heading for comparison (parts[0] may start with "# ")
            part_heading = part.split("\n", 1)[0]
            full_heading = part_heading if i == 0 else f"## {part_heading}"
            if full_heading.strip() == heading.strip():
                # Replace body
                parts[i] = f"{part_heading}\n{new_content}\n"
                return "\n## ".join(parts)

        # Section not found — append
        separator = "\n" if text.endswith("\n") else "\n\n"
        return text + separator + f"## {section}\n{new_content}\n"
