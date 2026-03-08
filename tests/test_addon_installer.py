"""Unit tests for core/addon_installer.py"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from core.ami_paths import AmiPaths
from core.addon_installer import AddonInstaller, REQUIRED_MANIFEST_FIELDS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def paths(tmp_path):
    p = AmiPaths(root=str(tmp_path / "amini"))
    p.ensure_dirs()
    return p


@pytest.fixture
def installer(paths):
    return AddonInstaller(paths)


def _make_agent_dir(base: Path, manifest_extra: dict = None, missing_process=False, missing_get_tools=False) -> Path:
    """Write a minimal valid agent repo to base/."""
    base.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "test-agent",
        "version": "1.0.0",
        "entry_class": "TestAgent",
        "description": "A test agent",
    }
    if manifest_extra:
        manifest.update(manifest_extra)
    (base / "manifest.json").write_text(json.dumps(manifest))

    lines = ["from agents.base_agent import BaseAgent\n", "class TestAgent(BaseAgent):\n"]
    if not missing_process:
        lines.append("    def process(self, text): return text\n")
    if not missing_get_tools:
        lines.append("    def get_tools(self): return []\n")
    (base / "agent.py").write_text("".join(lines))
    return base


# ---------------------------------------------------------------------------
# _load_manifest
# ---------------------------------------------------------------------------

class TestLoadManifest:
    def test_raises_when_no_manifest(self, installer, tmp_path):
        with pytest.raises(FileNotFoundError, match="manifest.json"):
            installer._load_manifest(tmp_path)

    def test_raises_when_field_missing(self, installer, tmp_path):
        (tmp_path / "manifest.json").write_text(json.dumps({"name": "x"}))
        with pytest.raises(ValueError, match="missing"):
            installer._load_manifest(tmp_path)

    def test_returns_manifest_dict(self, installer, tmp_path):
        data = {"name": "a", "version": "1", "entry_class": "A"}
        (tmp_path / "manifest.json").write_text(json.dumps(data))
        result = installer._load_manifest(tmp_path)
        assert result["name"] == "a"

    def test_all_required_fields_accepted(self, installer, tmp_path):
        data = {f: "x" for f in REQUIRED_MANIFEST_FIELDS}
        (tmp_path / "manifest.json").write_text(json.dumps(data))
        result = installer._load_manifest(tmp_path)
        assert set(result.keys()) == REQUIRED_MANIFEST_FIELDS


# ---------------------------------------------------------------------------
# _validate_interface
# ---------------------------------------------------------------------------

class TestValidateInterface:
    def test_raises_when_no_agent_py(self, installer, tmp_path):
        with pytest.raises(FileNotFoundError, match="agent.py"):
            installer._validate_interface(tmp_path)

    def test_raises_when_process_missing(self, installer, tmp_path):
        _make_agent_dir(tmp_path, missing_process=True)
        with pytest.raises(ValueError, match="process"):
            installer._validate_interface(tmp_path)

    def test_raises_when_get_tools_missing(self, installer, tmp_path):
        _make_agent_dir(tmp_path, missing_get_tools=True)
        with pytest.raises(ValueError, match="get_tools"):
            installer._validate_interface(tmp_path)

    def test_passes_for_valid_agent(self, installer, tmp_path):
        _make_agent_dir(tmp_path)
        installer._validate_interface(tmp_path)  # no exception


# ---------------------------------------------------------------------------
# _run_pre_install_tests
# ---------------------------------------------------------------------------

class TestPreInstallTests:
    def test_skips_when_no_tests_dir(self, installer, tmp_path, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            installer._run_pre_install_tests(tmp_path)
        assert "skipping" in caplog.text.lower()

    def test_raises_when_tests_fail(self, installer, tmp_path):
        (tmp_path / "tests").mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            with pytest.raises(RuntimeError, match="Pre-install unit tests failed"):
                installer._run_pre_install_tests(tmp_path)

    def test_passes_when_tests_succeed(self, installer, tmp_path):
        (tmp_path / "tests").mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            installer._run_pre_install_tests(tmp_path)  # no exception

    def test_runs_pytest_with_unit_filter(self, installer, tmp_path):
        (tmp_path / "tests").mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            installer._run_pre_install_tests(tmp_path)
        cmd = mock_run.call_args[0][0]
        assert sys.executable in cmd
        assert "-m" in cmd
        assert "pytest" in cmd
        assert "-k" in cmd
        assert "unit" in cmd


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------

class TestUninstall:
    def test_raises_for_unknown_agent(self, installer):
        with pytest.raises(FileNotFoundError, match="not installed"):
            installer.uninstall("nonexistent-agent")

    def test_removes_agent_dir(self, installer, paths):
        agent_dir = paths.agent_dir("my-agent")
        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.py").write_text("# stub")
        installer.uninstall("my-agent")
        assert not agent_dir.exists()


# ---------------------------------------------------------------------------
# install (integration of steps, git cloned via mock)
# ---------------------------------------------------------------------------

class TestInstall:
    def _patch_clone(self, tmp_path, agent_dir_name="agent"):
        """Return a side_effect for subprocess.run that writes a valid agent dir."""
        def fake_clone(cmd, **kwargs):
            dest = Path(cmd[-1])
            _make_agent_dir(dest)
            return MagicMock(returncode=0)
        return fake_clone

    def test_install_calls_pre_install_tests_before_copy(self, installer, tmp_path, paths):
        call_order = []

        def fake_run(cmd, **kwargs):
            if "clone" in cmd:
                dest = Path(cmd[-1])
                _make_agent_dir(dest)
                (dest / "tests").mkdir()  # presence triggers pre-install test run
                return MagicMock(returncode=0)
            if "pytest" in cmd:
                call_order.append("pytest")
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run), \
             patch.object(installer, "_run_post_install_test"):
            installer.install("user/test-agent")

        assert "pytest" in call_order

    def test_install_writes_to_agents_dir(self, installer, paths):
        def fake_run(cmd, **kwargs):
            if "clone" in cmd:
                dest = Path(cmd[-1])
                _make_agent_dir(dest)
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run), \
             patch.object(installer, "_run_post_install_test"):
            name = installer.install("user/test-agent")

        assert name == "test-agent"
        assert paths.agent_dir("test-agent").exists()
        assert (paths.agent_dir("test-agent") / "agent.py").exists()

    def test_install_resolves_shorthand_github_url(self, installer, paths):
        seen_urls = []

        def fake_clone(cmd, **kwargs):
            seen_urls.append(cmd[3])  # git clone --depth=1 <url> <dest>
            dest = Path(cmd[-1])
            _make_agent_dir(dest)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_clone), \
             patch.object(installer, "_run_pre_install_tests"), \
             patch.object(installer, "_run_post_install_test"):
            installer.install("someuser/some-agent")

        assert seen_urls[0] == "https://github.com/someuser/some-agent"

    def test_install_uses_full_url_unchanged(self, installer, paths):
        seen_urls = []

        def fake_clone(cmd, **kwargs):
            seen_urls.append(cmd[3])  # git clone --depth=1 <url> <dest>
            dest = Path(cmd[-1])
            _make_agent_dir(dest)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_clone), \
             patch.object(installer, "_run_pre_install_tests"), \
             patch.object(installer, "_run_post_install_test"):
            installer.install("https://github.com/user/agent")

        assert seen_urls[0] == "https://github.com/user/agent"
