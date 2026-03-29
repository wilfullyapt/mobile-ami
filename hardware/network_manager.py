import logging
import subprocess
import threading
import time

logger = logging.getLogger(__name__)


class NetworkManager:
    """
    Manages the device's network state machine:
      offline  → WiFi radio off
      hotspot  → Pi broadcasts a hotspot (nmcli)
      wifi     → Pi connects to a saved WiFi network

    Action-button hold cycles through: offline → hotspot → wifi → offline.
    When entering wifi state with no internet after rollover_timeout_sec,
    the manager automatically falls back to hotspot mode.

    Registered callbacks are notified on every state change so other
    components (e.g. DeviceServer) can react accordingly.
    """

    _STATES = ["offline", "hotspot", "wifi"]

    def __init__(self, config: dict):
        dev = config.get("device", {})
        self._hotspot_ssid = dev.get("hotspot_ssid", "AminiAI")
        self._hotspot_password = dev.get("hotspot_password", "amini123")
        self._rollover_timeout = dev.get("wifi_rollover_timeout_sec", 20)
        self.state = "offline"
        self._callbacks: list = []

    # ------------------------------------------------------------------
    # State change callbacks
    # ------------------------------------------------------------------

    def add_state_change_callback(self, fn) -> None:
        """Register a callable(new_state: str) called on every state change."""
        self._callbacks.append(fn)

    def _notify(self) -> None:
        for cb in self._callbacks:
            cb(self.state)

    # ------------------------------------------------------------------
    # State cycling (called by action button hold or API)
    # ------------------------------------------------------------------

    def cycle_state(self) -> None:
        """Advance to the next state in the cycle: offline → hotspot → wifi → offline."""
        idx = self._STATES.index(self.state)
        self.state = self._STATES[(idx + 1) % len(self._STATES)]
        self._apply_state()
        self._notify()

    def switch_to(self, state: str) -> None:
        """
        Directly switch to a specific state, bypassing cycle order.
        Used internally for auto-rollover and by the WiFi portal.
        """
        if state not in self._STATES:
            raise ValueError(f"Unknown network state: {state!r}")
        self.state = state
        self._apply_state()
        self._notify()

    def _apply_state(self) -> None:
        if self.state == "hotspot":
            subprocess.run(
                [
                    "nmcli", "dev", "wifi", "hotspot",
                    "ifname", "wlan0",
                    "ssid", self._hotspot_ssid,
                    "password", self._hotspot_password,
                ],
                capture_output=True,
            )
        elif self.state == "offline":
            subprocess.run(["nmcli", "radio", "wifi", "off"], capture_output=True)
        else:  # wifi
            subprocess.run(["nmcli", "radio", "wifi", "on"], capture_output=True)
            # Spawn rollover watcher so if no connection forms, fall back to hotspot
            threading.Thread(target=self._wifi_rollover_check, daemon=True).start()

    # ------------------------------------------------------------------
    # WiFi auto-rollover
    # ------------------------------------------------------------------

    def _wifi_rollover_check(self) -> None:
        """
        Background thread: if still in wifi state after rollover_timeout_sec
        with no internet connectivity, automatically switch to hotspot so the
        user can reconfigure via the portal.
        """
        time.sleep(self._rollover_timeout)
        if self.state == "wifi" and not self.has_internet():
            logger.warning(
                "No internet after %ds in wifi state — rolling over to hotspot",
                self._rollover_timeout,
            )
            self.switch_to("hotspot")

    # ------------------------------------------------------------------
    # WiFi connection management
    # ------------------------------------------------------------------

    def scan_networks(self) -> list[dict]:
        """
        Return list of visible WiFi access points sorted by signal strength.
        Each entry: {"ssid": str, "signal": int (0-100), "security": str}.
        """
        subprocess.run(["nmcli", "dev", "wifi", "rescan"], capture_output=True)
        result = subprocess.run(
            ["nmcli", "-t", "-f", "ssid,signal,security", "dev", "wifi", "list"],
            capture_output=True,
            text=True,
        )
        networks: list[dict] = []
        seen: set[str] = set()
        for line in result.stdout.splitlines():
            parts = line.split(":", 2)
            ssid = parts[0].strip()
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            try:
                signal = int(parts[1]) if len(parts) > 1 else 0
            except ValueError:
                signal = 0
            security = parts[2].strip() if len(parts) > 2 else ""
            networks.append({"ssid": ssid, "signal": signal, "security": security})

        return sorted(networks, key=lambda x: x["signal"], reverse=True)

    def connect_wifi(self, ssid: str, password: str) -> bool:
        """
        Connect to a WiFi network. nmcli saves the connection profile so
        subsequent radio-on transitions auto-connect.
        Returns True on success.
        """
        result = subprocess.run(
            ["nmcli", "dev", "wifi", "connect", ssid, "password", password],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("Connected to WiFi SSID '%s'", ssid)
        else:
            logger.warning("Failed to connect to '%s': %s", ssid, result.stderr.strip())
        return result.returncode == 0

    def forget_network(self, ssid: str) -> None:
        """Delete the saved nmcli connection profile for the given SSID."""
        subprocess.run(
            ["nmcli", "connection", "delete", "id", ssid],
            capture_output=True,
        )
        logger.info("Forgot WiFi network '%s'", ssid)

    def get_saved_networks(self) -> list[str]:
        """Return SSIDs of all saved nmcli WiFi connection profiles."""
        result = subprocess.run(
            ["nmcli", "-t", "-f", "name,type", "connection", "show"],
            capture_output=True,
            text=True,
        )
        ssids: list[str] = []
        for line in result.stdout.splitlines():
            if ":802-11-wireless" in line or ":wifi" in line:
                ssids.append(line.split(":", 1)[0])
        return ssids

    # ------------------------------------------------------------------
    # Network info queries
    # ------------------------------------------------------------------

    def has_internet(self) -> bool:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", "8.8.8.8"], capture_output=True
        )
        return result.returncode == 0

    def get_device_ip(self) -> str:
        """Return the first IP address reported by the system (wlan0 or similar)."""
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if parts:
                return parts[0]
        return "unknown"

    @property
    def ssid(self) -> str:
        """
        Return the relevant SSID for display:
          hotspot mode → the hotspot SSID we're broadcasting
          wifi mode    → the connected network's SSID (via nmcli)
          offline      → empty string
        """
        if self.state == "hotspot":
            return self._hotspot_ssid
        if self.state == "wifi":
            result = subprocess.run(
                ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                if line.startswith("yes:"):
                    return line.split(":", 1)[1]
        return ""
