"""
Status and settings routes.

Blueprint prefix: (none — top-level /api/status, /api/settings, /api/agents)
"""

import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("status", __name__)


def _va():
    from flask import current_app
    return current_app.config["VOICE_ASSISTANT"]


@bp.route("/api/status")
def api_status():
    try:
        return jsonify(_va().get_status())
    except Exception as exc:
        logger.error("GET /api/status failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/agents")
def api_agents():
    try:
        return jsonify({"agents": _va().agent_manager.slugs})
    except Exception as exc:
        logger.error("GET /api/agents failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/agent/cycle", methods=["POST"])
def api_agent_cycle():
    try:
        va = _va()
        va.cycle_agent()
        return jsonify({"agent": va.agent_manager.current})
    except Exception as exc:
        logger.error("POST /api/agent/cycle failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/agent/set/<slug>", methods=["POST"])
def api_agent_set(slug: str):
    try:
        va = _va()
        if slug not in va.agent_manager.slugs:
            return jsonify({"error": f"Unknown agent: {slug!r}"}), 404
        va.agent_manager.set_agent(slug)
        va.display.update_mode(slug)
        return jsonify({"agent": slug})
    except Exception as exc:
        logger.error("POST /api/agent/set/%s failed: %s", slug, exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/settings", methods=["GET"])
def api_settings_get():
    try:
        return jsonify(_va().get_settings())
    except Exception as exc:
        logger.error("GET /api/settings failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/settings", methods=["POST"])
def api_settings_post():
    try:
        va = _va()
        data = request.get_json(force=True, silent=True) or {}
        for key, value in data.items():
            va.update_setting(key, value)
        return jsonify(va.get_settings())
    except Exception as exc:
        logger.error("POST /api/settings failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
