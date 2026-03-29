"""Tests for hardware/network_manager.py — subprocess mocked."""
from unittest.mock import MagicMock, call, patch


_CONFIG = {
    "device": {
        "hotspot_ssid": "AminiAI",
        "hotspot_password": "amini123",
    }
}


def _make_nm():
    from hardware.network_manager import NetworkManager
    return NetworkManager(_CONFIG)


def test_initial_state_is_offline():
    nm = _make_nm()
    assert nm.state == "offline"


def test_cycle_offline_to_hotspot():
    nm = _make_nm()
    with patch("hardware.network_manager.subprocess.run") as mock_run:
        nm.cycle_state()
    assert nm.state == "hotspot"


def test_cycle_hotspot_to_wifi():
    nm = _make_nm()
    nm.state = "hotspot"
    with patch("hardware.network_manager.subprocess.run"):
        nm.cycle_state()
    assert nm.state == "wifi"


def test_cycle_wifi_to_offline():
    nm = _make_nm()
    nm.state = "wifi"
    with patch("hardware.network_manager.subprocess.run"):
        nm.cycle_state()
    assert nm.state == "offline"


def test_cycle_wraps_around():
    nm = _make_nm()
    with patch("hardware.network_manager.subprocess.run"):
        nm.cycle_state()   # offline → hotspot
        nm.cycle_state()   # hotspot → wifi
        nm.cycle_state()   # wifi → offline
    assert nm.state == "offline"


def test_apply_hotspot_calls_correct_nmcli():
    nm = _make_nm()
    nm.state = "offline"
    with patch("hardware.network_manager.subprocess.run") as mock_run:
        nm.cycle_state()   # → hotspot
    args = mock_run.call_args[0][0]
    assert "hotspot" in args
    assert "AminiAI" in args
    assert "amini123" in args


def test_apply_offline_calls_wifi_off():
    nm = _make_nm()
    nm.state = "wifi"
    with patch("hardware.network_manager.subprocess.run") as mock_run:
        nm.cycle_state()   # → offline
    args = mock_run.call_args[0][0]
    assert "off" in args


def test_apply_wifi_calls_wifi_on():
    nm = _make_nm()
    nm.state = "hotspot"
    with patch("hardware.network_manager.subprocess.run") as mock_run:
        nm.cycle_state()   # → wifi
    args = mock_run.call_args[0][0]
    assert "on" in args


def test_callbacks_called_on_state_change():
    nm = _make_nm()
    cb = MagicMock()
    nm.add_state_change_callback(cb)
    with patch("hardware.network_manager.subprocess.run"):
        nm.cycle_state()
    cb.assert_called_once_with("hotspot")


def test_multiple_callbacks_all_called():
    nm = _make_nm()
    cb1, cb2 = MagicMock(), MagicMock()
    nm.add_state_change_callback(cb1)
    nm.add_state_change_callback(cb2)
    with patch("hardware.network_manager.subprocess.run"):
        nm.cycle_state()
    cb1.assert_called_once()
    cb2.assert_called_once()


def test_has_internet_returns_true_on_zero_exit():
    nm = _make_nm()
    result = MagicMock(returncode=0)
    with patch("hardware.network_manager.subprocess.run", return_value=result):
        assert nm.has_internet() is True


def test_has_internet_returns_false_on_nonzero_exit():
    nm = _make_nm()
    result = MagicMock(returncode=1)
    with patch("hardware.network_manager.subprocess.run", return_value=result):
        assert nm.has_internet() is False


def test_get_device_ip_parses_hostname_output():
    nm = _make_nm()
    result = MagicMock(returncode=0, stdout="192.168.1.42 fe80::1\n")
    with patch("hardware.network_manager.subprocess.run", return_value=result):
        assert nm.get_device_ip() == "192.168.1.42"


def test_get_device_ip_returns_unknown_on_failure():
    nm = _make_nm()
    result = MagicMock(returncode=1, stdout="")
    with patch("hardware.network_manager.subprocess.run", return_value=result):
        assert nm.get_device_ip() == "unknown"


def test_ssid_property_in_hotspot_mode():
    nm = _make_nm()
    nm.state = "hotspot"
    assert nm.ssid == "AminiAI"


def test_ssid_property_in_offline_mode():
    nm = _make_nm()
    nm.state = "offline"
    assert nm.ssid == ""


def test_ssid_property_in_wifi_mode_parses_nmcli():
    nm = _make_nm()
    nm.state = "wifi"
    result = MagicMock(returncode=0, stdout="no:OtherNet\nyes:HomeWiFi\n")
    with patch("hardware.network_manager.subprocess.run", return_value=result):
        assert nm.ssid == "HomeWiFi"
