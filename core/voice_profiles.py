"""
Voice profile management for family member identification.

Profiles live at ~/.amini/profiles/:
    family.json              — list of enrolled profile metadata
    embeddings/<name>.npy   — 256-dim speaker embedding for each member

Identification is purely local — no audio or embeddings ever leave the device.

Typical flow:
    manager = VoiceProfileManager(paths.profiles_dir)
    encoder = orchestrator.get(ModelRole.SPEAKER)

    # Enroll:
    manager.enroll("Mom", audio_array, encoder, role="parent")

    # Identify at runtime:
    profile, confidence = manager.identify(audio_array, encoder)
    if profile:
        print(f"Hello, {profile.name}!")   # e.g. "Hello, Mom!"
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from core.models.wrappers.speaker_encoder import SpeakerEncoder

logger = logging.getLogger(__name__)

# Cosine-similarity threshold above which we declare a confident match.
# 0.75 is conservative — tune down to ~0.70 for more permissive matching
# (e.g. noisy environments or when members have similar voices).
_IDENTIFY_THRESHOLD = 0.75

# Minimum audio duration (seconds at 16 kHz) for a reliable embedding.
# Clips shorter than this are likely to produce noisy embeddings.
_MIN_SAMPLES = 16000 * 1  # 1 second


@dataclass
class VoiceProfile:
    """Metadata for a single enrolled family member."""
    name: str           # Display name, e.g. "Mom", "Jake"
    role: str           # "parent" | "child" | "teen" | "guest"
    age_group: str      # "adult" | "teen" | "child"
    color: str = "white"          # LED accent colour for this member
    preferences: dict = field(default_factory=dict)  # free-form per-person settings


class VoiceProfileManager:
    """
    Enroll, identify, and manage family voice profiles.

    All state is persisted to disk; the in-memory dict is kept in sync.
    Thread safety: single-threaded access assumed (called from pipeline).
    """

    def __init__(self, profiles_dir: Path):
        self._dir = profiles_dir
        self._embeddings_dir = profiles_dir / "embeddings"
        self._meta_path = profiles_dir / "family.json"
        self._profiles: dict[str, VoiceProfile] = {}
        self._load()

    # ------------------------------------------------------------------
    # Enrollment
    # ------------------------------------------------------------------

    def enroll(
        self,
        name: str,
        audio: np.ndarray,
        encoder: "SpeakerEncoder",
        role: str = "adult",
        age_group: str = "adult",
        color: str = "white",
        preferences: Optional[dict] = None,
    ) -> VoiceProfile:
        """
        Compute a speaker embedding from ``audio`` and save it as a profile.
        Replaces any existing profile with the same name.

        Returns the newly created VoiceProfile.
        """
        if len(audio) < _MIN_SAMPLES:
            logger.warning(
                "Audio for '%s' is very short (%d samples). Embedding may be unreliable.",
                name,
                len(audio),
            )
        embedding = encoder.embed(audio)
        profile = VoiceProfile(
            name=name,
            role=role,
            age_group=age_group,
            color=color,
            preferences=preferences or {},
        )
        self._profiles[name] = profile
        self._save_embedding(name, embedding)
        self._save_meta()
        logger.info("Enrolled voice profile: %s (role=%s, age_group=%s)", name, role, age_group)
        return profile

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    def identify(
        self,
        audio: np.ndarray,
        encoder: "SpeakerEncoder",
        threshold: float = _IDENTIFY_THRESHOLD,
    ) -> tuple[Optional[VoiceProfile], float]:
        """
        Identify the speaker in ``audio`` against all enrolled profiles.

        Returns:
            (VoiceProfile, confidence)  — if a match is found above ``threshold``
            (None, best_score)          — if no profile is confident enough

        confidence is the cosine similarity [0, 1] of the best match.
        """
        if not self._profiles:
            return None, 0.0

        try:
            query_emb = encoder.embed(audio)
        except Exception as exc:
            logger.warning("Speaker embedding failed: %s", exc)
            return None, 0.0

        best_name: Optional[str] = None
        best_score = -1.0

        for name in self._profiles:
            stored_emb = self._load_embedding(name)
            if stored_emb is None:
                continue
            score = encoder.similarity(query_emb, stored_emb)
            if score > best_score:
                best_score = score
                best_name = name

        if best_name and best_score >= threshold:
            logger.info("Speaker identified: %s (confidence=%.2f)", best_name, best_score)
            return self._profiles[best_name], best_score

        logger.debug(
            "Speaker not identified (best_score=%.2f < threshold=%.2f)",
            best_score,
            threshold,
        )
        return None, best_score

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------

    def list_profiles(self) -> list[VoiceProfile]:
        """Return all enrolled profiles sorted by name."""
        return sorted(self._profiles.values(), key=lambda p: p.name)

    def get(self, name: str) -> Optional[VoiceProfile]:
        """Return a profile by name, or None if not found."""
        return self._profiles.get(name)

    def remove(self, name: str) -> bool:
        """
        Delete a profile and its embedding. Returns True if the profile existed.
        """
        if name not in self._profiles:
            return False
        del self._profiles[name]
        emb_path = self._embeddings_dir / f"{name}.npy"
        if emb_path.exists():
            emb_path.unlink()
        self._save_meta()
        logger.info("Removed voice profile: %s", name)
        return True

    def update_preferences(self, name: str, preferences: dict) -> bool:
        """Merge ``preferences`` into an existing profile. Returns False if not found."""
        profile = self._profiles.get(name)
        if profile is None:
            return False
        profile.preferences.update(preferences)
        self._save_meta()
        return True

    # ------------------------------------------------------------------
    # Persistence (private)
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._meta_path.exists():
            return
        try:
            data = json.loads(self._meta_path.read_text())
            for entry in data:
                p = VoiceProfile(**entry)
                self._profiles[p.name] = p
            logger.debug("Loaded %d voice profile(s)", len(self._profiles))
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Could not load voice profiles from %s: %s", self._meta_path, exc)

    def _save_meta(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._meta_path.write_text(
            json.dumps([asdict(p) for p in self._profiles.values()], indent=2)
        )

    def _save_embedding(self, name: str, embedding: np.ndarray) -> None:
        self._embeddings_dir.mkdir(parents=True, exist_ok=True)
        np.save(str(self._embeddings_dir / f"{name}.npy"), embedding)

    def _load_embedding(self, name: str) -> Optional[np.ndarray]:
        path = self._embeddings_dir / f"{name}.npy"
        if not path.exists():
            return None
        try:
            return np.load(str(path))
        except Exception as exc:
            logger.warning("Could not load embedding for '%s': %s", name, exc)
            return None
