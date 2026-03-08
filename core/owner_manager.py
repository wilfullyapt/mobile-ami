"""
Owner management — links a vocal fingerprint to the device owner.

The owner is the specific family member this device "belongs to". The owner's
voice profile is the primary anchor for the ally agent's identity and loyalty.

State is persisted at ~/.amini/owner.json:
    {
      "name": str,               # display name matching a VoiceProfile entry
      "established_at": ISO8601, # when ownership was first established
      "last_seen_at": ISO8601    # last time the owner's voice was identified
    }

Without an owner the device is in "searching" state — the ally agent will
introduce itself and try to discover who it belongs to.

When the owner establishes themselves, VoiceProfileManager should have their
voice enrolled under the same name so the pipeline can identify them.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)


class OwnerManager:
    """
    Tracks the device owner and their last-seen timestamp.

    The owner name must correspond to an enrolled VoiceProfile entry.
    """

    def __init__(self, paths: "AmiPaths"):
        self._path = paths.owner_path
        self._data: dict = self._load()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def has_owner(self) -> bool:
        """True if an owner has been established."""
        return bool(self._data.get("name"))

    @property
    def owner_name(self) -> Optional[str]:
        return self._data.get("name")

    @property
    def established_at(self) -> Optional[datetime]:
        raw = self._data.get("established_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    @property
    def last_seen_at(self) -> Optional[datetime]:
        raw = self._data.get("last_seen_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def seconds_since_owner_seen(self) -> Optional[float]:
        """
        Return seconds elapsed since the owner was last identified by voice.
        Returns None if the owner has never been identified by voice.
        """
        if self.last_seen_at is None:
            return None
        delta = datetime.now(timezone.utc) - self.last_seen_at.replace(
            tzinfo=self.last_seen_at.tzinfo or timezone.utc
        )
        return max(0.0, delta.total_seconds())

    def is_owner_present(self, within_sec: float = 300.0) -> bool:
        """
        Return True if the owner's voice was identified within ``within_sec`` seconds.
        Uses the passed threshold; caller supplies the config value.
        """
        secs = self.seconds_since_owner_seen()
        return secs is not None and secs <= within_sec

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def establish(self, name: str) -> None:
        """
        Designate a family member as the device owner.
        Idempotent — calling again updates the name and resets the timestamp.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._data = {
            "name": name,
            "established_at": now,
            "last_seen_at": now,
        }
        self._save()
        logger.info("Owner established: %s", name)

    def record_seen(self, name: str) -> None:
        """
        Update last_seen_at when the owner's voice is identified in the pipeline.
        No-ops if the given name is not the established owner.
        """
        if name == self.owner_name:
            self._data["last_seen_at"] = datetime.now(timezone.utc).isoformat()
            self._save()

    # ------------------------------------------------------------------
    # Persistence (private)
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load owner.json: %s", exc)
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))
