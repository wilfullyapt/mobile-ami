"""Tests for core/device_server.py — uses Flask test client."""
import json
from unittest.mock import MagicMock, patch


def _make_va(agents=None):
    """Build a minimal VoiceAssistant mock for the device server."""
    va = MagicMock()
    slugs = agents or ["qa", "block_timer"]
    va.get_status.return_value = {
        "battery_pct": 80,
        "voltage": 4.1,
        "agent": "qa",
        "agents": slugs,
        "net_state": "hotspot",
        "ssid": "AminiAI",
        "has_internet": False,
        "hotword_trigger": True,
    }
    va.get_settings.return_value = {"hotword_trigger": True}
    va.agent_manager.slugs = slugs
    va.agent_manager.current = "qa"
    va.network.state = "hotspot"
    va.network.ssid = "AminiAI"
    va.network.get_device_ip.return_value = "192.168.4.1"
    va.network.has_internet.return_value = False
    va.network._hotspot_ssid = "AminiAI"
    va.paths = MagicMock()
    va.paths.list_agents.return_value = []
    return va


def _make_server(va=None):
    from core.server.job_manager import JobManager
    from core.device_server import DeviceServer
    va = va or _make_va()
    installer = MagicMock()
    conv_logger = MagicMock()
    conv_logger.get_history.return_value = []
    conv_logger.get_agents_with_history.return_value = []
    job_manager = JobManager()
    srv = DeviceServer(
        port=5000,
        voice_assistant=va,
        addon_installer=installer,
        conv_logger=conv_logger,
        job_manager=job_manager,
    )
    return srv, va


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------

def test_dashboard_returns_html():
    srv, _ = _make_server()
    client = srv._app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert b"Amini" in r.data


# ------------------------------------------------------------------
# Status + agent routes
# ------------------------------------------------------------------

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
    va.agent_manager.set_agent.assert_called_once_with("block_timer")


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


# ------------------------------------------------------------------
# Network routes
# ------------------------------------------------------------------

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


def test_api_wifi_connect_missing_ssid_returns_400():
    srv, _ = _make_server()
    client = srv._app.test_client()
    r = client.post(
        "/api/wifi/connect",
        data=json.dumps({"password": "secret"}),
        content_type="application/json",
    )
    assert r.status_code == 400


def test_api_wifi_connect_success():
    srv, va = _make_server()
    va.network.connect_wifi.return_value = True
    va.network.state = "wifi"
    client = srv._app.test_client()
    r = client.post(
        "/api/wifi/connect",
        data=json.dumps({"ssid": "HomeNet", "password": "secret"}),
        content_type="application/json",
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["ok"] is True
    va.network.connect_wifi.assert_called_once_with("HomeNet", "secret")


def test_api_wifi_connect_failure_returns_422():
    srv, va = _make_server()
    va.network.connect_wifi.return_value = False
    client = srv._app.test_client()
    r = client.post(
        "/api/wifi/connect",
        data=json.dumps({"ssid": "BadNet", "password": "wrong"}),
        content_type="application/json",
    )
    assert r.status_code == 422


def test_api_wifi_scan_returns_networks():
    srv, va = _make_server()
    va.network.scan_networks.return_value = [
        {"ssid": "HomeNet", "signal": 80, "security": "WPA2"},
        {"ssid": "GuestNet", "signal": 50, "security": ""},
    ]
    client = srv._app.test_client()
    r = client.get("/api/wifi/networks")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert len(data["networks"]) == 2
    assert data["networks"][0]["ssid"] == "HomeNet"


def test_api_wifi_saved_returns_list():
    srv, va = _make_server()
    va.network.get_saved_networks.return_value = ["HomeNet", "WorkNet"]
    client = srv._app.test_client()
    r = client.get("/api/wifi/saved")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "HomeNet" in data["networks"]


def test_api_wifi_forget_calls_forget():
    srv, va = _make_server()
    client = srv._app.test_client()
    r = client.delete("/api/wifi/saved/HomeNet")
    assert r.status_code == 200
    va.network.forget_network.assert_called_once_with("HomeNet")


# ------------------------------------------------------------------
# Plugin routes
# ------------------------------------------------------------------

def test_api_plugins_list_empty():
    srv, va = _make_server()
    va.paths.list_agents.return_value = []
    client = srv._app.test_client()
    r = client.get("/api/plugins")
    assert r.status_code == 200
    assert json.loads(r.data)["plugins"] == []


def test_api_plugins_install_starts_job():
    srv, _ = _make_server()
    client = srv._app.test_client()
    r = client.post(
        "/api/plugins/install",
        data=json.dumps({"source": "user/awesome-agent"}),
        content_type="application/json",
    )
    assert r.status_code == 202
    data = json.loads(r.data)
    assert "job_id" in data
    assert data["status"] == "running"


def test_api_plugins_install_missing_source_returns_400():
    srv, _ = _make_server()
    client = srv._app.test_client()
    r = client.post(
        "/api/plugins/install",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert r.status_code == 400


def test_api_plugins_remove_unknown_returns_404():
    srv, va = _make_server()
    srv._app.config["ADDON_INSTALLER"].uninstall.side_effect = FileNotFoundError
    client = srv._app.test_client()
    r = client.delete("/api/plugins/nonexistent")
    assert r.status_code == 404


def test_api_plugins_job_status_unknown_returns_404():
    srv, _ = _make_server()
    client = srv._app.test_client()
    r = client.get("/api/plugins/jobs/doesnotexist")
    assert r.status_code == 404


# ------------------------------------------------------------------
# Conversation routes
# ------------------------------------------------------------------

def test_api_conversations_empty():
    srv, _ = _make_server()
    client = srv._app.test_client()
    r = client.get("/api/conversations")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["conversations"] == []
    assert data["count"] == 0


def test_api_conversations_agents_empty():
    srv, _ = _make_server()
    client = srv._app.test_client()
    r = client.get("/api/conversations/agents")
    assert r.status_code == 200
    assert json.loads(r.data)["agents"] == []


def test_api_conversations_returns_filtered_by_agent():
    srv, _ = _make_server()
    conv_logger = srv._app.config["CONV_LOGGER"]
    conv_logger.get_history.return_value = [
        {"id": "x", "agent": "qa", "timestamp": "...", "transcript": "hi", "response": "hello"}
    ]
    client = srv._app.test_client()
    r = client.get("/api/conversations?agent=qa")
    assert r.status_code == 200
    conv_logger.get_history.assert_called_with(agent="qa", limit=100)


# ------------------------------------------------------------------
# Test runner routes
# ------------------------------------------------------------------

def test_api_test_run_starts_job():
    srv, _ = _make_server()
    client = srv._app.test_client()
    r = client.post("/api/test/run")
    assert r.status_code == 202
    data = json.loads(r.data)
    assert "job_id" in data


def test_api_test_run_unknown_agent_returns_404():
    srv, va = _make_server()
    va.paths.agent_dir.return_value = MagicMock(exists=lambda: False)
    client = srv._app.test_client()
    r = client.post("/api/test/run?agent=ghost")
    assert r.status_code == 404


def test_api_test_job_not_found():
    srv, _ = _make_server()
    client = srv._app.test_client()
    r = client.get("/api/test/jobs/nope")
    assert r.status_code == 404


def test_api_test_jobs_list_empty():
    srv, _ = _make_server()
    client = srv._app.test_client()
    r = client.get("/api/test/jobs")
    assert r.status_code == 200
    assert json.loads(r.data)["jobs"] == []


# ------------------------------------------------------------------
# Server lifecycle
# ------------------------------------------------------------------

def test_server_start_launches_thread():
    srv, _ = _make_server()
    with patch.object(srv, "_serve"):
        srv.start()
    assert srv._running is True
    assert srv._thread is not None


def test_server_start_idempotent():
    """Calling start() twice should not launch a second thread."""
    srv, _ = _make_server()
    with patch.object(srv, "_serve"):
        srv.start()
        thread_1 = srv._thread
        srv.start()
        thread_2 = srv._thread
    assert thread_1 is thread_2


def test_server_stop_clears_running_flag():
    srv, _ = _make_server()
    srv._running = True
    srv.stop()
    assert srv._running is False
