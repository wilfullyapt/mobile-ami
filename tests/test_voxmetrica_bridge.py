"""VoxMetrica bridge unit — no package required."""

from __future__ import annotations

from core.voxmetrica_bridge import VoxClaimProfile, maybe_build_bridge_from_env


def test_maybe_build_off_by_default(monkeypatch):
    monkeypatch.delenv("VOXMETRICA_ENABLED", raising=False)
    assert maybe_build_bridge_from_env() is None


def test_claim_profile_fields():
    p = VoxClaimProfile(name="Alex", speaker_id="alex", outcome="matched")
    assert p.name == "Alex"
    assert p.role == "adult"
