"""Unit tests for core/voice_profiles.py and core/speaker_encoder.py (mocked)."""

import json
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.voice_profiles import VoiceProfile, VoiceProfileManager, _IDENTIFY_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_encoder(embedding=None):
    """Return a mock SpeakerEncoder whose embed() returns a fixed embedding."""
    enc = MagicMock()
    if embedding is None:
        embedding = np.ones(256, dtype=np.float32) / np.sqrt(256)
    enc.embed.return_value = embedding
    enc.similarity.side_effect = lambda a, b: float(np.dot(a, b))
    return enc


def _make_manager(tmp_path) -> VoiceProfileManager:
    return VoiceProfileManager(tmp_path / "profiles")


# ---------------------------------------------------------------------------
# VoiceProfile dataclass
# ---------------------------------------------------------------------------

class TestVoiceProfile:
    def test_default_color_and_preferences(self):
        p = VoiceProfile(name="Alice", role="parent", age_group="adult")
        assert p.color == "white"
        assert p.preferences == {}

    def test_custom_fields(self):
        p = VoiceProfile(name="Jake", role="child", age_group="child", color="blue")
        assert p.name == "Jake"
        assert p.color == "blue"


# ---------------------------------------------------------------------------
# VoiceProfileManager — enrollment
# ---------------------------------------------------------------------------

class TestEnrollment:
    def test_enroll_creates_profile(self, tmp_path):
        mgr = _make_manager(tmp_path)
        enc = _make_encoder()
        audio = np.zeros(16000, dtype=np.float32)

        profile = mgr.enroll("Mom", audio, enc, role="parent", age_group="adult")

        assert profile.name == "Mom"
        assert profile.role == "parent"
        assert "Mom" in [p.name for p in mgr.list_profiles()]

    def test_enroll_persists_metadata(self, tmp_path):
        mgr = _make_manager(tmp_path)
        enc = _make_encoder()
        audio = np.zeros(16000, dtype=np.float32)
        mgr.enroll("Dad", audio, enc)

        # Reload from disk
        mgr2 = VoiceProfileManager(tmp_path / "profiles")
        assert any(p.name == "Dad" for p in mgr2.list_profiles())

    def test_enroll_saves_embedding_file(self, tmp_path):
        mgr = _make_manager(tmp_path)
        enc = _make_encoder()
        audio = np.zeros(16000, dtype=np.float32)
        mgr.enroll("Mom", audio, enc)

        emb_path = tmp_path / "profiles" / "embeddings" / "Mom.npy"
        assert emb_path.exists()

    def test_enroll_overwrites_existing_profile(self, tmp_path):
        mgr = _make_manager(tmp_path)
        enc = _make_encoder()
        audio = np.zeros(16000, dtype=np.float32)
        mgr.enroll("Mom", audio, enc, role="parent")
        mgr.enroll("Mom", audio, enc, role="guest")  # overwrite

        profiles = mgr.list_profiles()
        moms = [p for p in profiles if p.name == "Mom"]
        assert len(moms) == 1
        assert moms[0].role == "guest"

    def test_enroll_calls_encoder_embed(self, tmp_path):
        mgr = _make_manager(tmp_path)
        enc = _make_encoder()
        audio = np.zeros(16000, dtype=np.float32)
        mgr.enroll("Mom", audio, enc)
        enc.embed.assert_called_once_with(audio)


# ---------------------------------------------------------------------------
# VoiceProfileManager — identification
# ---------------------------------------------------------------------------

class TestIdentification:
    def _enroll_and_identify(self, tmp_path, query_emb, stored_emb):
        """Helper: enroll with stored_emb, then identify with query_emb."""
        mgr = _make_manager(tmp_path)

        # Custom encoder that returns stored_emb on first call, query_emb on second
        call_count = [0]
        base_emb = stored_emb / np.linalg.norm(stored_emb)
        query_norm = query_emb / np.linalg.norm(query_emb)

        enc_enroll = MagicMock()
        enc_enroll.embed.return_value = base_emb

        audio = np.zeros(16000, dtype=np.float32)
        mgr.enroll("Mom", audio, enc_enroll)

        enc_query = MagicMock()
        enc_query.embed.return_value = query_norm
        enc_query.similarity.side_effect = lambda a, b: float(np.dot(a, b))

        return mgr.identify(audio, enc_query)

    def test_returns_profile_when_above_threshold(self, tmp_path):
        emb = np.ones(256, dtype=np.float32)
        profile, score = self._enroll_and_identify(tmp_path, emb, emb)
        assert profile is not None
        assert profile.name == "Mom"
        assert score >= _IDENTIFY_THRESHOLD

    def test_returns_none_when_no_profiles(self, tmp_path):
        mgr = _make_manager(tmp_path)
        enc = _make_encoder()
        audio = np.zeros(16000, dtype=np.float32)
        profile, score = mgr.identify(audio, enc)
        assert profile is None
        assert score == 0.0

    def test_returns_none_when_score_below_threshold(self, tmp_path):
        stored = np.ones(256, dtype=np.float32)
        # Orthogonal vector → cosine similarity = 0
        query = np.zeros(256, dtype=np.float32)
        query[0] = 1.0
        stored[0] = 0.0
        stored[1] = 1.0
        profile, score = self._enroll_and_identify(tmp_path, query, stored)
        assert profile is None

    def test_embedding_exception_returns_none(self, tmp_path):
        mgr = _make_manager(tmp_path)
        enc_enroll = _make_encoder()
        audio = np.zeros(16000, dtype=np.float32)
        mgr.enroll("Mom", audio, enc_enroll)

        bad_enc = MagicMock()
        bad_enc.embed.side_effect = RuntimeError("model error")
        profile, score = mgr.identify(audio, bad_enc)
        assert profile is None


# ---------------------------------------------------------------------------
# VoiceProfileManager — remove / list / get
# ---------------------------------------------------------------------------

class TestManagement:
    def test_remove_existing_profile(self, tmp_path):
        mgr = _make_manager(tmp_path)
        enc = _make_encoder()
        audio = np.zeros(16000, dtype=np.float32)
        mgr.enroll("Mom", audio, enc)

        assert mgr.remove("Mom") is True
        assert mgr.get("Mom") is None

    def test_remove_deletes_embedding_file(self, tmp_path):
        mgr = _make_manager(tmp_path)
        enc = _make_encoder()
        audio = np.zeros(16000, dtype=np.float32)
        mgr.enroll("Mom", audio, enc)
        mgr.remove("Mom")

        emb_path = tmp_path / "profiles" / "embeddings" / "Mom.npy"
        assert not emb_path.exists()

    def test_remove_nonexistent_returns_false(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.remove("Nobody") is False

    def test_list_profiles_sorted_by_name(self, tmp_path):
        mgr = _make_manager(tmp_path)
        enc = _make_encoder()
        audio = np.zeros(16000, dtype=np.float32)
        mgr.enroll("Zara", audio, enc)
        mgr.enroll("Alice", audio, enc)
        names = [p.name for p in mgr.list_profiles()]
        assert names == sorted(names)

    def test_update_preferences(self, tmp_path):
        mgr = _make_manager(tmp_path)
        enc = _make_encoder()
        audio = np.zeros(16000, dtype=np.float32)
        mgr.enroll("Mom", audio, enc)
        mgr.update_preferences("Mom", {"theme": "dark"})
        assert mgr.get("Mom").preferences["theme"] == "dark"

    def test_update_preferences_nonexistent_returns_false(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.update_preferences("Ghost", {"x": 1}) is False

    def test_corrupted_metadata_loads_empty(self, tmp_path):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "family.json").write_text("NOT JSON{{{")
        mgr = VoiceProfileManager(profiles_dir)
        assert mgr.list_profiles() == []
