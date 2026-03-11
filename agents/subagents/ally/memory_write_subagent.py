"""
AllyMemoryWriteSubAgent — internal ally tool to write dated memory entries.

NOT registered in the global ToolRegistry. Only used inside AllyAgent's
own ``_tool_loop`` so the LLM can persist facts about the day.

Memory files live at: ~/.amini/data/ally/memory/<YYYY-MM-DD>.json
Each file is a flat JSON dict of {key: value} pairs.

Tool name: ``write_ally_memory``
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date
from typing import TYPE_CHECKING, Optional

from agents.tools.base_tool import BaseTool, ToolParam

if TYPE_CHECKING:
    from core.models.orchestrator import ModelOrchestrator
    from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)


class AllyMemoryWriteSubAgent(BaseTool):
    """Write a key/value pair to today's (or a specified date's) ally memory file."""

    name = "write_ally_memory"
    description = (
        "Store a fact or note in ally memory for a given date. "
        "Entries are saved to ~/.amini/data/ally/memory/<date>.json."
    )
    parameters = [
        ToolParam("key", "string", "Identifier for this memory entry", required=True),
        ToolParam("value", "string", "Value to store", required=True),
        ToolParam(
            "date",
            "string",
            "Date in YYYY-MM-DD format (defaults to today)",
            required=False,
        ),
    ]

    def __init__(self, orchestrator: "ModelOrchestrator", paths: "AmiPaths"):
        self._orch = orchestrator
        self._paths = paths

    def execute(self, key: str, value: str, date: Optional[str] = None) -> str:
        date_str = date or _today_str()
        mem_dir = self._paths.ally_memory_dir
        mem_dir.mkdir(parents=True, exist_ok=True)
        mem_file = mem_dir / f"{date_str}.json"

        try:
            existing = json.loads(mem_file.read_text()) if mem_file.exists() else {}
        except (json.JSONDecodeError, OSError):
            existing = {}

        existing[key] = value
        self._atomic_write(mem_file, existing)
        logger.info("write_ally_memory [%s] %s = %s", date_str, key, value)
        return f"Remembered [{date_str}] {key} = {value}"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _atomic_write(path, data: dict) -> None:
        directory = path.parent
        with tempfile.NamedTemporaryFile(
            mode="w", dir=directory, delete=False, suffix=".tmp"
        ) as tmp:
            json.dump(data, tmp, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, path)


def _today_str() -> str:
    return date.today().isoformat()
