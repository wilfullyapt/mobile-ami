import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)


class ConversationLogger:
    """
    Persists voice interaction transcripts and agent responses to disk.

    Each conversation is stored as a JSON file:
        ~/.amini/conversations/<agent>/<timestamp>-<uid>.json

    File format:
        {
            "id": "20260308T143022-a1b2c3",
            "agent": "qa",
            "timestamp": "2026-03-08T14:30:22.000000+00:00",
            "transcript": "What's the weather like?",
            "response": "I don't have internet access..."
        }
    """

    def __init__(self, paths: AmiPaths):
        self._paths = paths

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def log(self, agent: str, transcript: str, response: str) -> str:
        """
        Save a conversation entry. Returns the conversation ID.
        Silently no-ops if agent, transcript, or response is empty.
        """
        if not (agent and transcript and response):
            return ""

        agent_dir = self._paths.conversation_agent_dir(agent)
        agent_dir.mkdir(parents=True, exist_ok=True)

        conv_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            + "-"
            + uuid.uuid4().hex[:6]
        )
        entry = {
            "id": conv_id,
            "agent": agent,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "transcript": transcript,
            "response": response,
        }

        path = agent_dir / f"{conv_id}.json"
        fd, tmp = tempfile.mkstemp(dir=agent_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(entry, f, indent=2)
            os.replace(tmp, path)
        except Exception as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            logger.error("Failed to save conversation entry: %s", exc)
            return ""

        logger.debug("Logged conversation %s for agent '%s'", conv_id, agent)
        return conv_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_history(self, agent: str = None, limit: int = 100) -> list[dict]:
        """
        Return conversations in reverse chronological order.
        Pass agent=None to retrieve across all agents.
        """
        conv_dir = self._paths.conversations_dir
        if not conv_dir.exists():
            return []

        if agent:
            agent_dirs = [conv_dir / agent]
        else:
            agent_dirs = [d for d in conv_dir.iterdir() if d.is_dir()]

        entries = []
        for ag_dir in agent_dirs:
            if not ag_dir.exists():
                continue
            for f in ag_dir.glob("*.json"):
                try:
                    entries.append(json.loads(f.read_text()))
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Skipping unreadable conversation file %s: %s", f, exc)

        entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return entries[:limit]

    def get_agents_with_history(self) -> list[str]:
        """Return list of agent slugs that have conversation history."""
        conv_dir = self._paths.conversations_dir
        if not conv_dir.exists():
            return []
        return sorted(d.name for d in conv_dir.iterdir() if d.is_dir())
