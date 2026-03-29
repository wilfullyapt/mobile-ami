"""Tests for new NetworkManager capabilities (WiFi connect, scan, rollover)."""
import threading
import time
from unittest.mock import MagicMock, patch

_CONFIG = {
    "device": {
        "hotspot_ssid": "AminiAI",
        "hotspot_password": "amini123",
        "wifi_rollover_timeout_sec": 1,  # short timeout for tests
    }
}


def _make_nm():
    from hardware.network_manager import NetworkManager
    return NetworkManager(_CONFIG)


# ------------------------------------------------------------------
# switch_to()
# ------------------------------------------------------------------

def test_switch_to_sets_state_directly():
    nm = _make_nm()
    with patch("hardware.network_manager.subprocess.run"):
        nm.switch_to("hotspot")
    assert nm.state == "hotspot"


def test_switch_to_notifies_callbacks():
    nm = _make_nm()
    cb = MagicMock()
    nm.add_state_change_callback(cb)
    with patch("hardware.network_manager.subprocess.run"):
        nm.switch_to("hotspot")
    cb.assert_called_once_with("hotspot")


def test_switch_to_unknown_state_raises():
    import pytest
    nm = _make_nm()
    with pytest.raises(ValueError):
        nm.switch_to("flying")


# ------------------------------------------------------------------
# connect_wifi()
# ------------------------------------------------------------------

def test_connect_wifi_returns_true_on_success():
    nm = _make_nm()
    result = MagicMock(returncode=0, stderr="")
    with patch("hardware.network_manager.subprocess.run", return_value=result):
        assert nm.connect_wifi("HomeNet", "secret") is True


def test_connect_wifi_returns_false_on_failure():
    nm = _make_nm()
    result = MagicMock(returncode=1, stderr="Error: Connection failed")
    with patch("hardware.network_manager.subprocess.run", return_value=result):
        assert nm.connect_wifi("BadNet", "wrong") is False


def test_connect_wifi_calls_nmcli_with_correct_args():
    nm = _make_nm()
    result = MagicMock(returncode=0, stderr="")
    with patch("hardware.network_manager.subprocess.run", return_value=result) as mock_run:
        nm.connect_wifi("MySSID", "MyPass")
    args = mock_run.call_args[0][0]
    assert "connect" in args
    assert "MySSID" in args
    assert "MyPass" in args


# ------------------------------------------------------------------
# scan_networks()
# ------------------------------------------------------------------

def test_scan_networks_parses_nmcli_output():
    nm = _make_nm()
    nmcli_output = "HomeNet:85:WPA2\nGuestNet:45:\nOpenNet:30:\n"
    result_rescan = MagicMock(returncode=0)
    result_list = MagicMock(returncode=0, stdout=nmcli_output)

    with patch("hardware.network_manager.subprocess.run",
               side_effect=[result_rescan, result_list]):
        networks = nm.scan_networks()

    assert len(networks) == 3
    assert networks[0]["ssid"] == "HomeNet"
    assert networks[0]["signal"] == 85
    assert networks[0]["security"] == "WPA2"
    # Sorted descending by signal
    assert networks[0]["signal"] >= networks[1]["signal"]


def test_scan_networks_deduplicates_ssids():
    nm = _make_nm()
    nmcli_output = "HomeNet:85:WPA2\nHomeNet:80:WPA2\nOther:50:\n"
    result_rescan = MagicMock(returncode=0)
    result_list = MagicMock(returncode=0, stdout=nmcli_output)

    with patch("hardware.network_manager.subprocess.run",
               side_effect=[result_rescan, result_list]):
        networks = nm.scan_networks()

    ssids = [n["ssid"] for n in networks]
    assert ssids.count("HomeNet") == 1


def test_scan_networks_skips_blank_ssids():
    nm = _make_nm()
    nmcli_output = ":60:WPA2\nHomeNet:85:WPA2\n"
    result_rescan = MagicMock(returncode=0)
    result_list = MagicMock(returncode=0, stdout=nmcli_output)

    with patch("hardware.network_manager.subprocess.run",
               side_effect=[result_rescan, result_list]):
        networks = nm.scan_networks()

    assert all(n["ssid"] for n in networks)


# ------------------------------------------------------------------
# forget_network()
# ------------------------------------------------------------------

def test_forget_network_calls_nmcli_delete():
    nm = _make_nm()
    result = MagicMock(returncode=0)
    with patch("hardware.network_manager.subprocess.run", return_value=result) as mock_run:
        nm.forget_network("HomeNet")
    args = mock_run.call_args[0][0]
    assert "delete" in args
    assert "HomeNet" in args


# ------------------------------------------------------------------
# get_saved_networks()
# ------------------------------------------------------------------

def test_get_saved_networks_parses_wifi_connections():
    nm = _make_nm()
    nmcli_output = "HomeNet:802-11-wireless\nEthernet:802-3-ethernet\nWorkNet:802-11-wireless\n"
    result = MagicMock(returncode=0, stdout=nmcli_output)
    with patch("hardware.network_manager.subprocess.run", return_value=result):
        saved = nm.get_saved_networks()
    assert "HomeNet" in saved
    assert "WorkNet" in saved
    assert "Ethernet" not in saved


# ------------------------------------------------------------------
# WiFi auto-rollover
# ------------------------------------------------------------------

def test_wifi_state_starts_rollover_thread():
    """Entering wifi state launches the rollover watcher thread."""
    nm = _make_nm()
    rollover_called = threading.Event()

    original_check = nm._wifi_rollover_check

    def patched_check():
        rollover_called.set()

    with patch("hardware.network_manager.subprocess.run"):
        nm._wifi_rollover_check = patched_check
        nm.switch_to("wifi")

    assert rollover_called.wait(timeout=2)


def test_wifi_rollover_switches_to_hotspot_when_no_internet():
    """After timeout with no internet, state should become hotspot."""
    nm = _make_nm()
    # has_internet always returns False
    with patch("hardware.network_manager.subprocess.run"):
        with patch.object(nm, "has_internet", return_value=False):
            nm.switch_to("wifi")
            # Wait for rollover (timeout is 1s in test config)
            time.sleep(2)

    assert nm.state == "hotspot"


def test_wifi_rollover_does_not_switch_when_internet_available():
    """Rollover should not fire if internet becomes available."""
    nm = _make_nm()
    with patch("hardware.network_manager.subprocess.run"):
        with patch.object(nm, "has_internet", return_value=True):
            nm.switch_to("wifi")
            time.sleep(2)

    assert nm.state == "wifi"


def test_wifi_rollover_does_not_switch_if_state_changed():
    """If user manually left wifi state before timeout, rollover does nothing."""
    nm = _make_nm()
    with patch("hardware.network_manager.subprocess.run"):
        with patch.object(nm, "has_internet", return_value=False):
            nm.switch_to("wifi")
            nm.state = "offline"   # manually change state before timeout fires
            time.sleep(2)

    assert nm.state == "offline"
