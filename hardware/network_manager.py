import subprocess


class NetworkManager:
    """
    Manages the device's network state machine:
      offline  → WiFi radio off
      hotspot  → Pi broadcasts a hotspot (nmcli)
      wifi     → Pi connects to a local WiFi network

    Action-button hold cycles through: offline → hotspot → wifi → offline.

    Registered callbacks are notified on every state change so other
    components (e.g. DeviceServer) can start/stop accordingly.
    """

    _STATES = ["offline", "hotspot", "wifi"]

    def __init__(self, config: dict):
        dev = config.get("device", {})
        self._hotspot_ssid = dev.get("hotspot_ssid", "AminiAI")
        self._hotspot_password = dev.get("hotspot_password", "amini123")
        self.state = "offline"
        self._callbacks: list = []

    # ------------------------------------------------------------------
    # State change callbacks
    # ------------------------------------------------------------------

    def add_state_change_callback(self, fn) -> None:
        """Register a callable(new_state: str) to be called on state changes."""
        self._callbacks.append(fn)

    # ------------------------------------------------------------------
    # State cycling (called by action button hold)
    # ------------------------------------------------------------------

    def cycle_state(self) -> None:
        idx = self._STATES.index(self.state)
        self.state = self._STATES[(idx + 1) % len(self._STATES)]
        self._apply_state()
        for cb in self._callbacks:
            cb(self.state)

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
