"""
Conversation history routes.

Endpoints:
  GET /api/conversations                   — all history (most recent first)
  GET /api/conversations?agent=<slug>      — filtered by agent
  GET /api/conversations/agents            — list agents that have history
"""

import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("conversations", __name__)


def _conv_logger():
    from flask import current_app
    return current_app.config["CONV_LOGGER"]


@bp.route("/api/conversations")
def api_conversations():
    try:
        agent = request.args.get("agent") or None
        limit_str = request.args.get("limit", "100")
        try:
            limit = max(1, min(int(limit_str), 500))
        except ValueError:
            limit = 100
        history = _conv_logger().get_history(agent=agent, limit=limit)
        return jsonify({"conversations": history, "count": len(history)})
    except Exception as exc:
        logger.error("GET /api/conversations failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/conversations/agents")
def api_conversations_agents():
    try:
        return jsonify({"agents": _conv_logger().get_agents_with_history()})
    except Exception as exc:
        logger.error("GET /api/conversations/agents failed: %s", exc)
        return jsonify({"error": str(exc)}), 500
