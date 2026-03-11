"""
MemorySubAgent — persistent key-value memory stored in ~/.amini/memory.json.

Primary tool:   memory_store(key, value)
Additional tool: memory_recall(key)
"""
from __future__ import annotations

import json
import logging
import tempfile
import os
from typing import TYPE_CHECKING, Optional

from agents.base_sub_agent import BaseSubAgent
from agents.tools.base_tool import BaseTool, ToolParam

if TYPE_CHECKING:
    from core.models.orchestrator import ModelOrchestrator
    from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)

_MEMORY_FILENAME = "memory.json"


class _MemoryRecallTool(BaseTool):
    name = "memory_recall"
    description = "Recall a previously stored memory value by key."
    parameters = [
        ToolParam("key", "string", "The key to look up in persistent memory", required=True),
    ]

    def __init__(self, memory_path):
        self._path = memory_path

    def execute(self, key: str) -> str:
        try:
            data = json.loads(self._path.read_text()) if self._path.exists() else {}
        except (json.JSONDecodeError, OSError):
            data = {}
        if key in data:
            return f"{key}: {data[key]}"
        return f"No memory found for key '{key}'."


class MemorySubAgent(BaseSubAgent):
    """Persists arbitrary key-value pairs to ~/.amini/memory.json."""

    name = "memory_store"
    description = "Store a piece of information for later recall."
    parameters = [
        ToolParam("key", "string", "Identifier for this memory", required=True),
        ToolParam("value", "string", "Value to remember", required=True),
    ]

    def __init__(
        self,
        orchestrator: "ModelOrchestrator",
        paths: "Optional[AmiPaths]" = None,
    ):
        super().__init__(orchestrator, paths)
        self._memory_path = (paths.root / _MEMORY_FILENAME) if paths else None

    def execute(self, key: str, value: str) -> str:
        if self._memory_path is None:
            return "Memory storage unavailable (no paths configured)."
        try:
            data = json.loads(self._memory_path.read_text()) if self._memory_path.exists() else {}
        except (json.JSONDecodeError, OSError):
            data = {}
        data[key] = value
        self._atomic_write(data)
        logger.info("memory_store: %s = %s", key, value)
        return f"Remembered: {key} = {value}"

    def _atomic_write(self, data: dict) -> None:
        directory = self._memory_path.parent
        with tempfile.NamedTemporaryFile(
            mode="w", dir=directory, delete=False, suffix=".tmp"
        ) as tmp:
            json.dump(data, tmp, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, self._memory_path)

    def get_additional_tools(self) -> list[BaseTool]:
        return [_MemoryRecallTool(self._memory_path)]
