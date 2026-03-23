"""
Config management routes.

Provides safe, validated read/write access to config.yaml via the
ConfigManager whitelist.  Changes to agent enable/disable and sub-agent
equip take effect immediately (live reload via AgentManager).  Changes to
device settings take effect immediately where possible (display timeout,
hotspot creds are read on next use).

Endpoints
---------
GET  /api/config/agents
     List all agents (built-in + add-ons) with enabled state and per-agent
     sub-agent equip state.

POST /api/config/agents/<slug>/toggle
     {enabled: bool}  — enable or disable an agent immediately.

POST /api/config/agents/<slug>/sub-agents
     {equipped_sub_agents: ["memory", "timer"]}  — update equip for one agent.

GET  /api/config/device
     Read current editable device/update settings.

POST /api/config/device
     Update one or more device settings.
"""

import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("config", __name__)


def _va():
    from flask import current_app
    return current_app.config["VOICE_ASSISTANT"]


def _cm():
    from flask import current_app
    return current_app.config["CONFIG_MANAGER"]


# ------------------------------------------------------------------
# Agent listing
# ------------------------------------------------------------------

@bp.route("/api/config/agents")
def api_config_agents():
    try:
        agents = _va().agent_manager.get_all_agent_metadata()
        return jsonify({"agents": agents})
    except Exception as exc:
        logger.error("GET /api/config/agents failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ------------------------------------------------------------------
# Agent enable / disable (live)
# ------------------------------------------------------------------

@bp.route("/api/config/agents/<slug>/toggle", methods=["POST"])
def api_config_agent_toggle(slug: str):
    try:
        data = request.get_json(force=True, silent=True) or {}
        enabled = bool(data.get("enabled", True))
        am = _va().agent_manager
        if enabled:
            am.enable_agent(slug)
        else:
            am.disable_agent(slug)
        return jsonify({"slug": slug, "enabled": enabled})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        logger.error("POST /api/config/agents/%s/toggle failed: %s", slug, exc)
        return jsonify({"error": str(exc)}), 500


# ------------------------------------------------------------------
# Sub-agent equip (live)
# ------------------------------------------------------------------

@bp.route("/api/config/agents/<slug>/sub-agents", methods=["POST"])
def api_config_agent_sub_agents(slug: str):
    try:
        data = request.get_json(force=True, silent=True) or {}
        equipped = data.get("equipped_sub_agents")
        if not isinstance(equipped, list):
            return jsonify({"error": "equipped_sub_agents must be a list"}), 400
        # Validate: each element must be a string
        if not all(isinstance(s, str) for s in equipped):
            return jsonify({"error": "equipped_sub_agents must be a list of strings"}), 400

        _va().agent_manager.update_equipped_sub_agents(slug, equipped)
        return jsonify({"slug": slug, "equipped_sub_agents": equipped})
    except Exception as exc:
        logger.error("POST /api/config/agents/%s/sub-agents failed: %s", slug, exc)
        return jsonify({"error": str(exc)}), 500


# ------------------------------------------------------------------
# Device settings
# ------------------------------------------------------------------

_VALID_DEVICE_KEYS = {
    "display_timeout_sec",
    "hotspot_ssid",
    "hotspot_password",
    "auto_update_enabled",
    "auto_update_channel",
    "device_server_port",
}


@bp.route("/api/config/device")
def api_config_device_get():
    try:
        cm = _cm()
        return jsonify({
            "display_timeout_sec": cm.get("device", "display_timeout_sec", default=15),
            "hotspot_ssid":        cm.get("device", "hotspot_ssid", default="AminiAI"),
            "hotspot_password":    cm.get("device", "hotspot_password", default="amini123"),
            "auto_update_enabled": cm.get("auto_update", "enabled", default=True),
            "auto_update_channel": cm.get("auto_update", "channel", default="stable"),
            "device_server_port":  cm.get("device_server", "port", default=5000),
        })
    except Exception as exc:
        logger.error("GET /api/config/device failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/config/device", methods=["POST"])
def api_config_device_post():
    try:
        cm = _cm()
        data = request.get_json(force=True, silent=True) or {}
        invalid = [k for k in data if k not in _VALID_DEVICE_KEYS]
        if invalid:
            return jsonify({"error": "Unknown settings", "invalid_keys": invalid}), 400

        for key, value in data.items():
            cm.set_device_setting(key, value)

        # Return current values after update
        return api_config_device_get()
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception as exc:
        logger.error("POST /api/config/device failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
