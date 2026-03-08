"""Tests for core/updater.py — subprocess, battery, and filesystem mocked."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# smbus2 is mocked in conftest.py; also mock hardware.power at module level
sys.modules.setdefault("hardware.power", MagicMock(get_battery=MagicMock(return_value=(80, 4.1))))

from core.updater import AutoUpdater  # noqa: E402


_CONFIG = {
    "auto_update": {
        "enabled": False,   # disable background thread during tests
        "channel": "stable",
        "check_interval_sec": 1800,
        "min_battery_pct": 30,
        "health_check_retries": 1,
        "repo_path": "/fake/repo",
    }
}


def _make_updater(network=None, config=None):
    network = network or MagicMock(state="wifi", has_internet=MagicMock(return_value=True))
    config = config or _CONFIG
    return AutoUpdater(network, config)


# ------------------------------------------------------------------
# Initialisation
# ------------------------------------------------------------------

def test_repo_path_from_config():
    u = _make_updater()
    assert u.repo_path == "/fake/repo"


def test_repo_path_autodetect_when_null():
    cfg = {
        "auto_update": {
            **_CONFIG["auto_update"],
            "repo_path": None,
            "enabled": False,
        }
    }
    u = _make_updater(config=cfg)
    # Should resolve to the project root (parent of core/)
    assert Path(u.repo_path).name in ("mobile-ami", "core") or Path(u.repo_path).is_dir()


def test_enabled_false_does_not_start_thread():
    u = _make_updater()
    # thread is not started when enabled=False
    assert not hasattr(u, "thread") or not getattr(getattr(u, "thread", None), "is_alive", lambda: False)()


# ------------------------------------------------------------------
# _get_current_tag
# ------------------------------------------------------------------

def test_get_current_tag_parses_git_output():
    u = _make_updater()
    r = MagicMock(returncode=0, stdout="stable-1.2.3\n")
    with patch("core.updater.subprocess.run", return_value=r):
        assert u._get_current_tag() == "stable-1.2.3"


def test_get_current_tag_returns_fallback_on_failure():
    u = _make_updater()
    r = MagicMock(returncode=1, stdout="")
    with patch("core.updater.subprocess.run", return_value=r):
        assert u._get_current_tag() == "0.0.0"


# ------------------------------------------------------------------
# _get_latest_tag
# ------------------------------------------------------------------

def test_get_latest_tag_returns_first_tag():
    u = _make_updater()
    fetch_result = MagicMock(returncode=0)
    tags_result = MagicMock(returncode=0, stdout="stable-2.0.0\nstable-1.9.0\n")
    with patch("core.updater.subprocess.run", side_effect=[fetch_result, tags_result]):
        assert u._get_latest_tag() == "stable-2.0.0"


def test_get_latest_tag_returns_none_when_no_tags():
    u = _make_updater()
    fetch_result = MagicMock(returncode=0)
    tags_result = MagicMock(returncode=0, stdout="")
    with patch("core.updater.subprocess.run", side_effect=[fetch_result, tags_result]):
        assert u._get_latest_tag() is None


# ------------------------------------------------------------------
# _try_update
# ------------------------------------------------------------------

def test_try_update_skips_when_current_equals_latest():
    u = _make_updater()
    with patch.object(u, "_get_current_tag", return_value="stable-1.0.0"), \
         patch.object(u, "_get_latest_tag", return_value="stable-1.0.0"), \
         patch.object(u, "_perform_update") as mock_perform:
        u._try_update()
    mock_perform.assert_not_called()


def test_try_update_skips_when_no_latest_tag():
    u = _make_updater()
    with patch.object(u, "_get_current_tag", return_value="stable-1.0.0"), \
         patch.object(u, "_get_latest_tag", return_value=None), \
         patch.object(u, "_perform_update") as mock_perform:
        u._try_update()
    mock_perform.assert_not_called()


def test_try_update_performs_update_when_newer():
    u = _make_updater()
    with patch.object(u, "_get_current_tag", return_value="stable-1.0.0"), \
         patch.object(u, "_get_latest_tag", return_value="stable-2.0.0"), \
         patch.object(u, "_perform_update") as mock_perform, \
         patch.object(u, "_health_check", return_value=True):
        u._try_update()
    mock_perform.assert_called_once_with("stable-2.0.0")


def test_try_update_rolls_back_on_health_check_failure():
    u = _make_updater()
    with patch.object(u, "_get_current_tag", return_value="stable-1.0.0"), \
         patch.object(u, "_get_latest_tag", return_value="stable-2.0.0"), \
         patch.object(u, "_perform_update"), \
         patch.object(u, "_health_check", return_value=False), \
         patch.object(u, "_rollback") as mock_rollback:
        u._try_update()
    mock_rollback.assert_called_once()


def test_try_update_rolls_back_on_exception():
    u = _make_updater()
    with patch.object(u, "_get_current_tag", return_value="stable-1.0.0"), \
         patch.object(u, "_get_latest_tag", return_value="stable-2.0.0"), \
         patch.object(u, "_perform_update", side_effect=RuntimeError("git fail")), \
         patch.object(u, "_rollback") as mock_rollback:
        u._try_update()
    mock_rollback.assert_called_once()


# ------------------------------------------------------------------
# Loop guards
# ------------------------------------------------------------------

def test_loop_skips_when_offline():
    network = MagicMock(state="offline", has_internet=MagicMock(return_value=False))
    u = _make_updater(network=network)
    calls = []
    with patch.object(u, "_try_update", side_effect=lambda: calls.append(1)), \
         patch("core.updater.get_battery", return_value=(80, 4.1)), \
         patch("core.updater.time.sleep", side_effect=[None, StopIteration]):
        try:
            u._loop()
        except StopIteration:
            pass
    assert len(calls) == 0


def test_loop_skips_when_battery_low():
    network = MagicMock(state="wifi", has_internet=MagicMock(return_value=True))
    u = _make_updater(network=network)
    calls = []
    with patch.object(u, "_try_update", side_effect=lambda: calls.append(1)), \
         patch("core.updater.get_battery", return_value=(20, 3.5)), \
         patch("core.updater.time.sleep", side_effect=[None, StopIteration]):
        try:
            u._loop()
        except StopIteration:
            pass
    assert len(calls) == 0


# ------------------------------------------------------------------
# Health check
# ------------------------------------------------------------------

def test_health_check_returns_true_when_healthy_file_appears():
    u = _make_updater()
    with tempfile.TemporaryDirectory() as tmp:
        u.repo_path = tmp
        healthy = Path(tmp, ".healthy")

        def write_on_first_sleep(_):
            # Write the file when sleep is first called (simulates service restart)
            healthy.write_text("ok")

        with patch("core.updater.time.sleep", side_effect=write_on_first_sleep):
            result = u._health_check()
    assert result is True


def test_health_check_returns_false_on_timeout():
    u = _make_updater()
    with tempfile.TemporaryDirectory() as tmp:
        u.repo_path = tmp
        # Do NOT write .healthy → should time out
        with patch("core.updater.time.sleep"):
            result = u._health_check()
    assert result is False


# ------------------------------------------------------------------
# mark_as_healthy
# ------------------------------------------------------------------

def test_mark_as_healthy_writes_file():
    u = _make_updater()
    with tempfile.TemporaryDirectory() as tmp:
        u.repo_path = tmp
        u.mark_as_healthy()
        assert (Path(tmp) / ".healthy").exists()
