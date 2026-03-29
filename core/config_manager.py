"""
ConfigManager — safe, validated read/write access to config.yaml.

Design
------
- On first run: if config.yaml doesn't exist, copies config.yaml.default → config.yaml.
- Exposes a whitelist (EDITABLE_PATHS) of keys the server is allowed to write.
  Hardware pins, model backends, etc. are read-only from the web UI.
- Atomic save: write to .tmp then os.rename to prevent partial writes.
- All mutating methods save immediately and broadcast a "reload" so that in-process
  readers (AgentManager, DeviceServer routes) see the new values.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

# Dot-path tuples of config keys the web UI is allowed to write.
# Everything else is read-only from the server.
EDITABLE_PATHS: set[tuple] = {
    ("device", "display_timeout_sec"),
    ("device", "hotspot_ssid"),
    ("device", "hotspot_password"),
    ("device_server", "port"),
    ("auto_update", "enabled"),
    ("auto_update", "channel"),
    ("agents", "exposed"),
    ("agents", "config"),          # entire sub-tree (validated per-set)
    ("ally", "threshold"),
    ("ally", "check_interval_sec"),
    ("ally", "interaction_mode"),
    ("ally", "soul_sections"),
    ("ally", "journal_snapshot_section"),
    ("ally", "soul_reorganize_interval_days"),
    ("ally", "journal_summary_last_n"),
}

# Friendly names for the device settings the UI exposes
DEVICE_SETTING_KEYS = {
    "display_timeout_sec",
    "hotspot_ssid",
    "hotspot_password",
}

AUTO_UPDATE_SETTING_KEYS = {
    "auto_update_enabled",   # maps to ("auto_update", "enabled")
    "auto_update_channel",   # maps to ("auto_update", "channel")
}

DEVICE_SERVER_SETTING_KEYS = {
    "device_server_port",    # maps to ("device_server", "port")
}


class ConfigManager:
    """
    Thread-safe config reader/writer.

    Usage
    -----
        cm = ConfigManager(Path("config.yaml"), Path("config.yaml.default"))
        cm.get("device", "hotspot_ssid")           # -> "AminiAI"
        cm.set("AminiSetup", "device", "hotspot_ssid")  # saves atomically
    """

    def __init__(self, config_path: Path, default_path: Path):
        self._config_path = config_path
        self._default_path = default_path
        self._data: dict = {}
        self._load()

    # ------------------------------------------------------------------
    # First-run bootstrap
    # ------------------------------------------------------------------

    @classmethod
    def ensure_config(cls, config_path: Path, default_path: Path) -> None:
        """
        If config_path does not exist, copy default_path → config_path.
        Called before VoiceAssistant is constructed so the first-run message
        is visible in the terminal.
        """
        config_path = Path(config_path)
        default_path = Path(default_path)
        if not config_path.exists():
            if not default_path.exists():
                logger.warning(
                    "Neither %s nor %s found — starting with empty config",
                    config_path, default_path,
                )
                return
            shutil.copy2(default_path, config_path)
            print(
                f"\n[amini] First run detected — config created from defaults.\n"
                f"        Edit settings at http://<device-ip>:5000 or in {config_path}\n"
            )
            logger.info("Created %s from %s", config_path, default_path)

    # ------------------------------------------------------------------
    # Read interface
    # ------------------------------------------------------------------

    def get(self, *keys: str, default: Any = None) -> Any:
        """Return the config value at the given key path, or *default*."""
        node = self._data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def raw(self) -> dict:
        """Return a shallow copy of the full config dict."""
        return dict(self._data)

    def reload(self) -> None:
        """Re-read config.yaml from disk (e.g. after an external edit)."""
        self._load()

    # ------------------------------------------------------------------
    # Write interface
    # ------------------------------------------------------------------

    def set(self, value: Any, *keys: str) -> None:
        """
        Set value at the given key path and save atomically.

        Raises
        ------
        PermissionError
            If the path is not in EDITABLE_PATHS.
        """
        if not self._is_editable(keys):
            raise PermissionError(
                f"Config path {'.'.join(keys)!r} is not editable via the server"
            )
        self._deep_set(self._data, list(keys), value)
        self._save()

    def set_agent_enabled(self, slug: str, enabled: bool) -> None:
        """Enable or disable a specific agent. Saves immediately."""
        self._ensure_agent_config(slug)
        self._data["agents"]["config"][slug]["enabled"] = enabled
        self._save()

    def set_agent_equipped_sub_agents(self, slug: str, equipped: list[str]) -> None:
        """Update the equipped_sub_agents list for an agent. Saves immediately."""
        self._ensure_agent_config(slug)
        self._data["agents"]["config"][slug]["equipped_sub_agents"] = list(equipped)
        self._save()

    def get_agent_config(self, slug: str) -> dict:
        """Return the config dict for *slug*, or defaults if absent."""
        return self._data.get("agents", {}).get("config", {}).get(slug, {
            "enabled": True,
            "equipped_sub_agents": [],
        })

    def set_device_setting(self, key: str, value: Any) -> None:
        """
        Update a device/auto_update/device_server setting by flat key.
        Flat keys: display_timeout_sec, hotspot_ssid, hotspot_password,
                   auto_update_enabled, auto_update_channel, device_server_port.
        """
        mapping = {
            "display_timeout_sec": ("device", "display_timeout_sec"),
            "hotspot_ssid":        ("device", "hotspot_ssid"),
            "hotspot_password":    ("device", "hotspot_password"),
            "auto_update_enabled": ("auto_update", "enabled"),
            "auto_update_channel": ("auto_update", "channel"),
            "device_server_port":  ("device_server", "port"),
        }
        if key not in mapping:
            raise KeyError(f"Unknown device setting: {key!r}")
        self.set(value, *mapping[key])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._config_path.exists():
            with open(self._config_path) as f:
                self._data = yaml.safe_load(f) or {}
        else:
            self._data = {}

    def _save(self) -> None:
        tmp = self._config_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True)
        os.replace(tmp, self._config_path)
        logger.debug("Config saved to %s", self._config_path)

    def _is_editable(self, keys: tuple) -> bool:
        """True if keys starts with any editable prefix."""
        for editable in EDITABLE_PATHS:
            if keys[:len(editable)] == editable:
                return True
        return False

    def _deep_set(self, node: dict, keys: list, value: Any) -> None:
        for k in keys[:-1]:
            if k not in node or not isinstance(node[k], dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = value

    def _ensure_agent_config(self, slug: str) -> None:
        """Make sure agents.config.<slug> dict exists."""
        if "agents" not in self._data:
            self._data["agents"] = {}
        if "config" not in self._data["agents"]:
            self._data["agents"]["config"] = {}
        if slug not in self._data["agents"]["config"]:
            self._data["agents"]["config"][slug] = {
                "enabled": True,
                "equipped_sub_agents": [],
            }
