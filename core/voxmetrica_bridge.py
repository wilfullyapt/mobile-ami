"""
Optional VoxMetrica bridge for mobile-ami.

When enabled, speaker ID uses voxmetrica.EdgeClient (hub gallery path / shared root)
instead of local Resemblyzer VoiceProfileManager as SoR. Resemblyzer remains a
fallback UX cache when the bridge is off or unavailable.

Config (settings / env):
  VOXMETRICA_ENABLED=1
  VOXMETRICA_ROOT=/path/to/gallery   # optional shared hub root
"""

from __future__ import annotations

import logging
import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class VoxClaimProfile:
    """Adapter shaped like VoiceProfile for pipeline compatibility."""

    name: str
    role: str = "adult"
    age_group: str = "adult"
    color: str = "white"
    speaker_id: str = ""
    outcome: str = "matched"
    claim: dict | None = None


class VoxMetricaBridge:
    """identify(audio_float_or_int16, encoder_ignored) → (profile|None, confidence)."""

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        ingress: str = "mobile-ami",
        session_id: str = "mobile",
        sample_rate: int = 16000,
    ):
        self.root = Path(root).expanduser() if root else None
        self.ingress = ingress
        self.session_id = session_id
        self.sample_rate = sample_rate
        self._client = None
        self.last_claim: dict[str, Any] | None = None
        self._load()

    def _load(self) -> None:
        try:
            from voxmetrica import EdgeClient  # type: ignore

            self._client = EdgeClient(self.root if self.root else None, ingress=self.ingress)
            logger.info("VoxMetrica bridge ready")
        except Exception as e:  # noqa: BLE001
            logger.warning("VoxMetrica bridge unavailable: %s", e)
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def identify(
        self,
        audio: np.ndarray,
        encoder: Any = None,
    ) -> Tuple[Optional[VoxClaimProfile], float]:
        if not self.available:
            return None, 0.0
        pcm = np.asarray(audio)
        if np.issubdtype(pcm.dtype, np.floating):
            pcm = (np.clip(pcm, -1.0, 1.0) * 32767.0).astype(np.int16)
        else:
            pcm = pcm.astype(np.int16).reshape(-1)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(pcm.tobytes())
            claim = self._client.identify(path, session_id=self.session_id)
            self.last_claim = claim
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

        if not claim or claim.get("outcome") != "matched":
            return None, float(claim.get("confidence") or 0.0) if claim else 0.0

        conf = float(claim.get("confidence") or 0.0)
        name = str(claim.get("display_name") or claim.get("speaker_id") or "Speaker")
        profile = VoxClaimProfile(
            name=name,
            role="adult",
            speaker_id=str(claim.get("speaker_id") or ""),
            outcome="matched",
            claim=claim,
        )
        return profile, conf

    def badge(self) -> str:
        if not self.available or not self.last_claim:
            return ""
        return str(self._client.badge(self.last_claim))


def maybe_build_bridge_from_env() -> Optional[VoxMetricaBridge]:
    if os.environ.get("VOXMETRICA_ENABLED", "").strip() not in ("1", "true", "yes", "on"):
        return None
    root = os.environ.get("VOXMETRICA_ROOT") or None
    return VoxMetricaBridge(root=root)
