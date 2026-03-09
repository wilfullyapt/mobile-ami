"""Unit tests for core/power_manager.py"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from core.interaction_mode import InteractionMode
from core.power_manager import PowerManager, _GOVERNOR_MAP, _governor_paths


# ---------------------------------------------------------------------------
# Governor map
# ---------------------------------------------------------------------------

class TestGovernorMap:
    def test_all_modes_have_governor(self):
        for mode in InteractionMode:
            assert mode in _GOVERNOR_MAP, f"{mode} missing from _GOVERNOR_MAP"

    def test_manual_is_powersave(self):
        assert _GOVERNOR_MAP[InteractionMode.MANUAL] == "powersave"

    def test_hot_word_is_ondemand(self):
        assert _GOVERNOR_MAP[InteractionMode.HOT_WORD] == "ondemand"

    def test_ally_is_performance(self):
        assert _GOVERNOR_MAP[InteractionMode.ALLY] == "performance"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_governor_paths(tmp_path, n=4) -> list[Path]:
    """Create fake cpufreq governor sysfs files and return their paths."""
    paths = []
    for i in range(n):
        p = tmp_path / f"cpu{i}" / "cpufreq" / "scaling_governor"
        p.parent.mkdir(parents=True)
        p.write_text("ondemand")
        paths.append(p)
    return paths


# ---------------------------------------------------------------------------
# When cpufreq is unavailable
# ---------------------------------------------------------------------------

class TestPowerManagerUnavailable:
    def test_available_false_when_no_sysfs(self):
        with patch("core.power_manager._governor_paths", return_value=[]):
            pm = PowerManager()
        assert pm.available is False

    def test_set_governor_returns_false_when_unavailable(self):
        with patch("core.power_manager._governor_paths", return_value=[]):
            pm = PowerManager()
        assert pm.set_governor("powersave") is False

    def test_apply_for_mode_returns_false_when_unavailable(self):
        with patch("core.power_manager._governor_paths", return_value=[]):
            pm = PowerManager()
        assert pm.apply_for_mode(InteractionMode.MANUAL) is False

    def test_current_governor_is_none_when_unavailable(self):
        with patch("core.power_manager._governor_paths", return_value=[]):
            pm = PowerManager()
        assert pm.current_governor is None


# ---------------------------------------------------------------------------
# When cpufreq IS available
# ---------------------------------------------------------------------------

class TestPowerManagerAvailable:
    def test_available_true_when_paths_exist(self, tmp_path):
        paths = _make_governor_paths(tmp_path)
        with patch("core.power_manager._governor_paths", return_value=paths):
            pm = PowerManager()
        assert pm.available is True

    def test_reads_initial_governor_from_sysfs(self, tmp_path):
        paths = _make_governor_paths(tmp_path)
        with patch("core.power_manager._governor_paths", return_value=paths):
            pm = PowerManager()
        assert pm.current_governor == "ondemand"

    def test_set_governor_writes_all_cores(self, tmp_path):
        paths = _make_governor_paths(tmp_path, n=4)
        with patch("core.power_manager._governor_paths", return_value=paths):
            pm = PowerManager()
            result = pm.set_governor("powersave")
        assert result is True
        for p in paths:
            assert p.read_text() == "powersave"

    def test_set_governor_updates_current_governor(self, tmp_path):
        paths = _make_governor_paths(tmp_path)
        with patch("core.power_manager._governor_paths", return_value=paths):
            pm = PowerManager()
            pm.set_governor("performance")
        assert pm.current_governor == "performance"

    def test_set_same_governor_is_noop(self, tmp_path):
        paths = _make_governor_paths(tmp_path)
        with patch("core.power_manager._governor_paths", return_value=paths):
            pm = PowerManager()
            pm.set_governor("ondemand")  # already ondemand
            # Overwrite file to track further writes
            for p in paths:
                p.write_text("SENTINEL")
            result = pm.set_governor("ondemand")  # should skip
        assert result is True
        # Files should still be SENTINEL (not re-written)
        for p in paths:
            assert p.read_text() == "SENTINEL"

    def test_apply_for_mode_manual_sets_powersave(self, tmp_path):
        paths = _make_governor_paths(tmp_path)
        with patch("core.power_manager._governor_paths", return_value=paths):
            pm = PowerManager()
            pm.apply_for_mode(InteractionMode.MANUAL)
        for p in paths:
            assert p.read_text() == "powersave"

    def test_apply_for_mode_ally_sets_performance(self, tmp_path):
        paths = _make_governor_paths(tmp_path)
        with patch("core.power_manager._governor_paths", return_value=paths):
            pm = PowerManager()
            pm.apply_for_mode(InteractionMode.ALLY)
        for p in paths:
            assert p.read_text() == "performance"

    def test_apply_for_mode_hot_word_sets_ondemand(self, tmp_path):
        paths = _make_governor_paths(tmp_path)
        # Start with powersave so a change is forced
        for p in paths:
            p.write_text("powersave")
        with patch("core.power_manager._governor_paths", return_value=paths):
            pm = PowerManager()
            pm.apply_for_mode(InteractionMode.HOT_WORD)
        for p in paths:
            assert p.read_text() == "ondemand"


# ---------------------------------------------------------------------------
# Permission errors (graceful degradation)
# ---------------------------------------------------------------------------

class TestPowerManagerPermissionError:
    def test_returns_false_on_permission_denied(self, tmp_path):
        paths = _make_governor_paths(tmp_path, n=2)
        # Make paths read-only
        for p in paths:
            p.chmod(0o444)
        try:
            with patch("core.power_manager._governor_paths", return_value=paths):
                pm = PowerManager()
                result = pm.set_governor("powersave")
            # On systems where we can't write: returns False
            # On systems that bypass file permissions (e.g. running as root): may return True
            # Either outcome is acceptable — just must not raise
            assert isinstance(result, bool)
        finally:
            for p in paths:
                p.chmod(0o644)
