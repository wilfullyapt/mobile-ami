"""Tests for core/device_server.py — uses Flask test client."""
import json
from unittest.mock import MagicMock, patch


def _make_va(agents=None):
    """Build a minimal VoiceAssistant mock for the device server."""
    va = MagicMock()
    va._settings = {"hotword_trigger": True}
    va.get_status.return_value = {
        "battery_pct": 80,
        "voltage": 4.1,
        "agent": "qa",
        "agents": agents or ["qa", "block_timer"],
        "net_state": "hotspot",
        "ssid": "AminiAI",
        "has_internet": False,
        "hotword_trigger": True,
    }
    va.agent_manager._slugs = agents or ["qa", "block_timer"]
    va.agent_manager.current = "qa"
    va.agent_manager._index = 0
    va.network.state = "hotspot"
    va.network.ssid = "AminiAI"
    va.network.get_device_ip.return_value = "192.168.4.1"
    va.network.has_internet.return_value = False
    return va


def _make_server(va=None):
    from core.device_server import DeviceServer
    va = va or _make_va()
    srv = DeviceServer(port=5000, voice_assistant=va)
    return srv, va


def test_dashboard_returns_html():
    srv, _ = _make_server()
    client = srv._app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert b"Amini" in r.data


def test_api_status_returns_json():
    srv, va = _make_server()
    client = srv._app.test_client()
    r = client.get("/api/status")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["battery_pct"] == 80
    assert data["agent"] == "qa"


def test_api_agent_cycle_calls_cycle_agent():
    srv, va = _make_server()
    client = srv._app.test_client()
    r = client.post("/api/agent/cycle")
    assert r.status_code == 200
    va.cycle_agent.assert_called_once()


def test_api_agent_set_known_slug():
    srv, va = _make_server()
    client = srv._app.test_client()
    r = client.post("/api/agent/set/block_timer")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["agent"] == "block_timer"


def test_api_agent_set_unknown_slug_returns_404():
    srv, va = _make_server()
    client = srv._app.test_client()
    r = client.post("/api/agent/set/nonexistent")
    assert r.status_code == 404


def test_api_agents_returns_list():
    srv, va = _make_server()
    client = srv._app.test_client()
    r = client.get("/api/agents")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "qa" in data["agents"]
    assert "block_timer" in data["agents"]


def test_api_settings_get():
    srv, va = _make_server()
    client = srv._app.test_client()
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "hotword_trigger" in data


def test_api_settings_post_calls_update_setting():
    srv, va = _make_server()
    client = srv._app.test_client()
    r = client.post(
        "/api/settings",
        data=json.dumps({"hotword_trigger": False}),
        content_type="application/json",
    )
    assert r.status_code == 200
    va.update_setting.assert_called_with("hotword_trigger", False)


def test_api_network_returns_state():
    srv, va = _make_server()
    client = srv._app.test_client()
    r = client.get("/api/network")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["state"] == "hotspot"
    assert data["ip"] == "192.168.4.1"


def test_api_network_cycle_calls_cycle_state():
    srv, va = _make_server()
    client = srv._app.test_client()
    r = client.post("/api/network/cycle")
    assert r.status_code == 200
    va.network.cycle_state.assert_called_once()


def test_server_start_launches_thread():
    srv, _ = _make_server()
    # Patch _serve so no real Flask server starts
    with patch.object(srv, "_serve"):
        srv.start()
    assert srv._running is True
    assert srv._thread is not None


def test_server_stop_clears_running_flag():
    srv, _ = _make_server()
    srv._running = True
    srv.stop()
    assert srv._running is False
