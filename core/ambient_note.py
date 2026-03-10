"""
AmbientNote — a timed chunk of ambient utterances captured by AllyListener.

Every ``ambient_chunk_sec`` (default 3 min), AllyListener flushes its
accumulated utterances into an AmbientNote and appends it to a pending
queue.  AllyAgent reads the queue via ``interval_listen`` to decide whether
to speak and to save important context.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class AmbientNote:
    """One timed chunk of ambient utterances."""

    chunk_index: int
    chunk_start: datetime        # timezone-aware UTC
    chunk_end: datetime          # timezone-aware UTC
    utterances: list             # list[AmbientUtterance] — avoid circular import
    unknown_clip_paths: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Human-readable formatting
    # ------------------------------------------------------------------

    def formatted_text(self) -> str:
        """
        Return a readable summary of all utterances in this chunk.

        Example lines::
            [420s ago, Mom (owner)]: What should I cook tonight?
            [380s ago, unknown]: I think pasta.
        """
        now = datetime.now(timezone.utc)
        lines: list[str] = []
        for u in self.utterances:
            ago = int((now - u.timestamp).total_seconds())
            who = u.speaker if u.speaker else "unknown"
            owner_tag = " (owner)" if u.is_owner else ""
            lines.append(f"[{ago}s ago, {who}{owner_tag}]: {u.text}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "chunk_index": self.chunk_index,
            "chunk_start": self.chunk_start.isoformat(),
            "chunk_end": self.chunk_end.isoformat(),
            "utterances": [
                {
                    "speaker": u.speaker,
                    "is_owner": u.is_owner,
                    "text": u.text,
                    "timestamp": u.timestamp.isoformat(),
                    "audio_duration_sec": u.audio_duration_sec,
                }
                for u in self.utterances
            ],
            "unknown_clip_paths": self.unknown_clip_paths,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AmbientNote":
        from core.ally_listener import AmbientUtterance

        utterances = [
            AmbientUtterance(
                speaker=u["speaker"],
                is_owner=u["is_owner"],
                text=u["text"],
                timestamp=datetime.fromisoformat(u["timestamp"]),
                audio_duration_sec=u.get("audio_duration_sec", 0.0),
            )
            for u in d.get("utterances", [])
        ]
        return cls(
            chunk_index=d["chunk_index"],
            chunk_start=datetime.fromisoformat(d["chunk_start"]),
            chunk_end=datetime.fromisoformat(d["chunk_end"]),
            utterances=utterances,
            unknown_clip_paths=d.get("unknown_clip_paths", []),
        )

    @classmethod
    def from_json(cls, text: str) -> "AmbientNote":
        return cls.from_dict(json.loads(text))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
