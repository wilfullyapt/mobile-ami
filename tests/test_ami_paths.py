"""Unit tests for core/ami_paths.py"""

import pytest
from pathlib import Path

from core.ami_paths import AmiPaths


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def paths(tmp_path):
    """AmiPaths rooted at a temp dir so tests never touch the real ~/.amini/."""
    return AmiPaths(root=str(tmp_path / "amini"))


# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------

class TestEnsureDirs:
    def test_creates_model_subdirs(self, paths):
        paths.ensure_dirs()
        for role in ("stt", "tts", "wake", "llm", "hailo"):
            assert (paths.models_dir / role).is_dir()

    def test_creates_agents_dir(self, paths):
        paths.ensure_dirs()
        assert paths.agents_dir.is_dir()

    def test_idempotent(self, paths):
        paths.ensure_dirs()
        paths.ensure_dirs()  # should not raise
        assert paths.agents_dir.is_dir()


class TestProperties:
    def test_root(self, tmp_path):
        p = AmiPaths(root=str(tmp_path / "amini"))
        assert p.root == (tmp_path / "amini").resolve()

    def test_models_dir(self, paths):
        assert paths.models_dir == paths.root / "models"

    def test_agents_dir(self, paths):
        assert paths.agents_dir == paths.root / "agents"

    def test_model_dir(self, paths):
        assert paths.model_dir("stt") == paths.models_dir / "stt"
        assert paths.model_dir("tts") == paths.models_dir / "tts"

    def test_agent_dir(self, paths):
        assert paths.agent_dir("my-agent") == paths.agents_dir / "my-agent"

    def test_agent_manifest(self, paths):
        assert paths.agent_manifest("x") == paths.agents_dir / "x" / "manifest.json"

    def test_agent_module(self, paths):
        assert paths.agent_module("x") == paths.agents_dir / "x" / "agent.py"


# ---------------------------------------------------------------------------
# Agent discovery
# ---------------------------------------------------------------------------

class TestListAgents:
    def test_empty_when_no_agents_dir(self, paths):
        assert paths.list_agents() == []

    def test_returns_dir_names(self, paths):
        paths.ensure_dirs()
        (paths.agents_dir / "alpha").mkdir()
        (paths.agents_dir / "beta").mkdir()
        assert paths.list_agents() == ["alpha", "beta"]

    def test_ignores_files(self, paths):
        paths.ensure_dirs()
        (paths.agents_dir / "real-agent").mkdir()
        (paths.agents_dir / "not-a-dir.txt").write_text("ignored")
        assert paths.list_agents() == ["real-agent"]

    def test_sorted(self, paths):
        paths.ensure_dirs()
        for name in ("zebra", "apple", "mango"):
            (paths.agents_dir / name).mkdir()
        assert paths.list_agents() == ["apple", "mango", "zebra"]


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

class TestResolveModelPath:
    def test_none_returns_model_dir(self, paths):
        result = paths.resolve_model_path("stt", None)
        assert result == str(paths.model_dir("stt"))

    def test_bare_filename_resolves_under_role_dir(self, paths):
        result = paths.resolve_model_path("tts", "en_US-lessac-medium.onnx")
        expected = str(paths.model_dir("tts") / "en_US-lessac-medium.onnx")
        assert result == expected

    def test_absolute_path_returned_unchanged(self, paths):
        result = paths.resolve_model_path("tts", "/opt/piper/model.onnx")
        assert result == "/opt/piper/model.onnx"

    def test_tilde_path_expanded(self, paths, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        result = paths.resolve_model_path("tts", "~/custom/model.onnx")
        assert result == str(tmp_path / "custom" / "model.onnx")
        assert not result.startswith("~")

    def test_different_roles_get_different_dirs(self, paths):
        stt = paths.resolve_model_path("stt", None)
        tts = paths.resolve_model_path("tts", None)
        assert stt != tts
        assert "stt" in stt
        assert "tts" in tts
