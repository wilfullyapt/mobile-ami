"""Unit tests for core/ally/system_prompt_manager.py"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from core.ally.system_prompt_manager import SystemPromptManager
from core.ami_paths import AmiPaths


@pytest.fixture
def paths(tmp_path):
    p = AmiPaths(root=str(tmp_path / "amini"))
    p.ensure_dirs()
    return p


@pytest.fixture
def default_file(tmp_path):
    f = tmp_path / "ally_system.md.default"
    f.write_text("# Default\n{{SOUL}}\nDefault content.")
    return tmp_path


class TestEnsure:
    def test_copies_default_when_absent(self, paths, default_file):
        mgr = SystemPromptManager(paths, project_root=default_file)
        assert not paths.ally_system_path.exists()
        mgr.ensure()
        assert paths.ally_system_path.exists()
        assert "Default content." in paths.ally_system_path.read_text()

    def test_does_not_overwrite_existing(self, paths, default_file):
        paths.ally_system_path.parent.mkdir(parents=True, exist_ok=True)
        paths.ally_system_path.write_text("user customized content")
        mgr = SystemPromptManager(paths, project_root=default_file)
        mgr.ensure()
        assert paths.ally_system_path.read_text() == "user customized content"

    def test_no_default_does_not_raise(self, paths, tmp_path):
        empty_root = tmp_path / "no_default"
        empty_root.mkdir()
        mgr = SystemPromptManager(paths, project_root=empty_root)
        mgr.ensure()  # Should warn but not raise


class TestRead:
    def test_reads_user_copy(self, paths, default_file):
        paths.ally_system_path.parent.mkdir(parents=True, exist_ok=True)
        paths.ally_system_path.write_text("my custom prompt")
        mgr = SystemPromptManager(paths, project_root=default_file)
        assert mgr.read() == "my custom prompt"

    def test_falls_back_to_default(self, paths, default_file):
        mgr = SystemPromptManager(paths, project_root=default_file)
        assert "Default content." in mgr.read()

    def test_returns_empty_string_when_neither_exists(self, paths, tmp_path):
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        mgr = SystemPromptManager(paths, project_root=empty_root)
        assert mgr.read() == ""


class TestWriteRaw:
    def test_write_creates_file(self, paths, default_file):
        mgr = SystemPromptManager(paths, project_root=default_file)
        mgr.write_raw("new content")
        assert paths.ally_system_path.read_text() == "new content"

    def test_write_overwrites_existing(self, paths, default_file):
        mgr = SystemPromptManager(paths, project_root=default_file)
        mgr.write_raw("first")
        mgr.write_raw("second")
        assert mgr.read() == "second"


class TestResetToDefault:
    def test_reset_copies_default_over_user_copy(self, paths, default_file):
        mgr = SystemPromptManager(paths, project_root=default_file)
        mgr.write_raw("user changes")
        result = mgr.reset_to_default()
        assert result is True
        assert "Default content." in mgr.read()

    def test_reset_returns_false_when_no_default(self, paths, tmp_path):
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        mgr = SystemPromptManager(paths, project_root=empty_root)
        result = mgr.reset_to_default()
        assert result is False


class TestExists:
    def test_false_when_not_created(self, paths, default_file):
        mgr = SystemPromptManager(paths, project_root=default_file)
        assert mgr.exists() is False

    def test_true_after_ensure(self, paths, default_file):
        mgr = SystemPromptManager(paths, project_root=default_file)
        mgr.ensure()
        assert mgr.exists() is True


class TestAmiPathsAllySystemPath:
    def test_ally_system_path_property(self, paths):
        assert paths.ally_system_path == paths.root / "ally_system.md"
