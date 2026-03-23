"""Unit tests for core/config_manager.py"""

import os
from pathlib import Path

import pytest
import yaml

from core.config_manager import ConfigManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_cfg(tmp_path) -> Path:
    p = tmp_path / "config.yaml.default"
    p.write_text(yaml.dump({
        "device": {
            "display_timeout_sec": 15,
            "hotspot_ssid": "AminiAI",
            "hotspot_password": "amini123",
        },
        "device_server": {"enabled": True, "port": 5000},
        "auto_update": {"enabled": True, "channel": "stable"},
        "agents": {
            "exposed": ["llm_response"],
            "config": {
                "llm_response": {"enabled": True, "equipped_sub_agents": ["memory", "timer"]},
            },
        },
    }))
    return p


@pytest.fixture
def config_path(tmp_path) -> Path:
    return tmp_path / "config.yaml"


@pytest.fixture
def cm(tmp_path, default_cfg, config_path) -> ConfigManager:
    ConfigManager.ensure_config(config_path, default_cfg)
    return ConfigManager(config_path, default_cfg)


# ---------------------------------------------------------------------------
# ensure_config
# ---------------------------------------------------------------------------

class TestEnsureConfig:
    def test_copies_default_when_missing(self, tmp_path, default_cfg, config_path, capsys):
        assert not config_path.exists()
        ConfigManager.ensure_config(config_path, default_cfg)
        assert config_path.exists()
        captured = capsys.readouterr()
        assert "First run" in captured.out

    def test_no_op_when_config_exists(self, tmp_path, default_cfg, config_path):
        config_path.write_text("existing: true\n")
        ConfigManager.ensure_config(config_path, default_cfg)
        assert yaml.safe_load(config_path.read_text()) == {"existing": True}

    def test_no_error_when_default_missing(self, tmp_path, config_path):
        missing = tmp_path / "no_default.yaml"
        ConfigManager.ensure_config(config_path, missing)
        assert not config_path.exists()  # nothing created


# ---------------------------------------------------------------------------
# get / set
# ---------------------------------------------------------------------------

class TestGetSet:
    def test_get_nested(self, cm):
        assert cm.get("device", "hotspot_ssid") == "AminiAI"

    def test_get_default(self, cm):
        assert cm.get("nonexistent", "key", default="fallback") == "fallback"

    def test_get_missing_path(self, cm):
        assert cm.get("device", "nonexistent") is None

    def test_set_editable_path(self, cm, config_path):
        cm.set("NewHotspot", "device", "hotspot_ssid")
        assert cm.get("device", "hotspot_ssid") == "NewHotspot"
        # Verify persisted
        on_disk = yaml.safe_load(config_path.read_text())
        assert on_disk["device"]["hotspot_ssid"] == "NewHotspot"

    def test_set_non_editable_raises(self, cm):
        with pytest.raises(PermissionError):
            cm.set("evil", "models", "stt", "backend")

    def test_atomic_save(self, cm, config_path):
        """Verify no .tmp file is left after save."""
        cm.set(20, "device", "display_timeout_sec")
        assert not (config_path.with_suffix(".tmp")).exists()

    def test_reload_picks_up_external_changes(self, cm, config_path):
        data = yaml.safe_load(config_path.read_text())
        data["device"]["hotspot_ssid"] = "Reloaded"
        config_path.write_text(yaml.dump(data))
        cm.reload()
        assert cm.get("device", "hotspot_ssid") == "Reloaded"


# ---------------------------------------------------------------------------
# Agent config helpers
# ---------------------------------------------------------------------------

class TestAgentConfig:
    def test_set_agent_enabled(self, cm, config_path):
        cm.set_agent_enabled("planning", False)
        assert cm.get_agent_config("planning")["enabled"] is False

    def test_set_agent_equipped(self, cm):
        cm.set_agent_equipped_sub_agents("planning", ["memory", "timer", "hardware"])
        assert cm.get_agent_config("planning")["equipped_sub_agents"] == ["memory", "timer", "hardware"]

    def test_get_agent_config_defaults_for_unknown(self, cm):
        cfg = cm.get_agent_config("nonexistent_agent")
        assert cfg["enabled"] is True
        assert cfg["equipped_sub_agents"] == []

    def test_ensure_agent_config_created(self, cm):
        cm.set_agent_enabled("brand_new", True)
        assert "brand_new" in cm.raw()["agents"]["config"]


# ---------------------------------------------------------------------------
# Device settings
# ---------------------------------------------------------------------------

class TestDeviceSettings:
    def test_set_device_setting_display(self, cm):
        cm.set_device_setting("display_timeout_sec", 30)
        assert cm.get("device", "display_timeout_sec") == 30

    def test_set_device_setting_port(self, cm):
        cm.set_device_setting("device_server_port", 8080)
        assert cm.get("device_server", "port") == 8080

    def test_set_device_setting_invalid_key(self, cm):
        with pytest.raises(KeyError):
            cm.set_device_setting("hardware_pins", [17, 27])

    def test_set_auto_update(self, cm):
        cm.set_device_setting("auto_update_enabled", False)
        assert cm.get("auto_update", "enabled") is False
        cm.set_device_setting("auto_update_channel", "beta")
        assert cm.get("auto_update", "channel") == "beta"
