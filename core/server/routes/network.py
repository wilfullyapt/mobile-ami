"""
Network management and WiFi portal routes.

Endpoints:
  GET  /api/network                 — current state, SSID, IP, internet flag
  POST /api/network/cycle           — advance state machine
  GET  /api/wifi/networks           — scan visible access points
  POST /api/wifi/connect            — connect to a network {ssid, password}
  GET  /api/wifi/saved              — list saved nmcli profiles
  DELETE /api/wifi/saved/<ssid>     — forget a saved network
"""

import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("network", __name__)


def _net():
    from flask import current_app
    return current_app.config["VOICE_ASSISTANT"].network


# ------------------------------------------------------------------
# General network state
# ------------------------------------------------------------------

@bp.route("/api/network")
def api_network():
    try:
        net = _net()
        return jsonify({
            "state": net.state,
            "ssid": net.ssid,
            "ip": net.get_device_ip(),
            "has_internet": net.has_internet(),
            "hotspot_ssid": net._hotspot_ssid,
        })
    except Exception as exc:
        logger.error("GET /api/network failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/network/cycle", methods=["POST"])
def api_network_cycle():
    try:
        net = _net()
        net.cycle_state()
        return jsonify({"state": net.state})
    except Exception as exc:
        logger.error("POST /api/network/cycle failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ------------------------------------------------------------------
# WiFi portal (used primarily in hotspot mode)
# ------------------------------------------------------------------

@bp.route("/api/wifi/networks")
def api_wifi_scan():
    """Scan for visible WiFi access points. May take a few seconds."""
    try:
        networks = _net().scan_networks()
        return jsonify({"networks": networks})
    except Exception as exc:
        logger.error("GET /api/wifi/networks failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/wifi/connect", methods=["POST"])
def api_wifi_connect():
    """
    Connect to a WiFi network and switch to wifi state.
    Body: {"ssid": "MyNetwork", "password": "secret"}
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        ssid = (data.get("ssid") or "").strip()
        password = data.get("password", "")
        if not ssid:
            return jsonify({"error": "ssid is required"}), 400

        net = _net()
        # Save the connection profile and attempt to connect
        connected = net.connect_wifi(ssid, password)
        if connected:
            # Switch state machine to wifi; rollover thread will validate
            if net.state != "wifi":
                net.switch_to("wifi")
            return jsonify({"ok": True, "ssid": ssid})
        else:
            return jsonify({"ok": False, "error": f"Could not connect to {ssid!r}"}), 422
    except Exception as exc:
        logger.error("POST /api/wifi/connect failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/wifi/saved")
def api_wifi_saved():
    try:
        return jsonify({"networks": _net().get_saved_networks()})
    except Exception as exc:
        logger.error("GET /api/wifi/saved failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/wifi/saved/<path:ssid>", methods=["DELETE"])
def api_wifi_forget(ssid: str):
    try:
        _net().forget_network(ssid)
        return jsonify({"ok": True, "forgotten": ssid})
    except Exception as exc:
        logger.error("DELETE /api/wifi/saved/%s failed: %s", ssid, exc)
        return jsonify({"error": str(exc)}), 500
