"""
Shared mutable context that flows through all agents.

AgentContext is created once in VoiceAssistant and passed to every
agent.process() call and lifecycle hooks. It is the single source of
truth for conversation history, per-agent memory namespaces, and
runtime mode flags.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

_MAX_HISTORY = 50


@dataclass
class AgentContext:
    history: list[dict] = field(default_factory=list)
    memory: dict = field(default_factory=dict)
    mode_flags: dict = field(default_factory=dict)
    current_speaker: Optional[str] = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def empty(cls) -> "AgentContext":
        return cls()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def add_message(self, role: str, content: str) -> None:
        """Append a message and trim history to _MAX_HISTORY entries."""
        self.history.append({"role": role, "content": content})
        if len(self.history) > _MAX_HISTORY:
            self.history = self.history[-_MAX_HISTORY:]

    def clear_history(self) -> None:
        self.history.clear()

    def recent_history(self, n: int = 10) -> list[dict]:
        return self.history[-n:] if n < len(self.history) else list(self.history)

    # ------------------------------------------------------------------
    # Per-agent memory namespace
    # ------------------------------------------------------------------

    def agent_memory(self, slug: str) -> dict:
        """Return the memory dict for *slug*, auto-initialising if absent."""
        if slug not in self.memory:
            self.memory[slug] = {}
        return self.memory[slug]

    # ------------------------------------------------------------------
    # Mode flags
    # ------------------------------------------------------------------

    def set_flag(self, key: str, value) -> None:
        self.mode_flags[key] = value

    def get_flag(self, key: str, default=None):
        return self.mode_flags.get(key, default)
