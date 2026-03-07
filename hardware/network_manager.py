import subprocess

class NetworkManager:
    def __init__(self):
        self.state = "connected"
        self.ssid = "MyVoiceAI"

    def has_internet(self):
        result = subprocess.run(["ping", "-c", "1", "-W", "2", "8.8.8.8"], capture_output=True)
        return result.returncode == 0

    def cycle_state(self):
        states = ["connected", "hotspot", "offline"]
        idx = states.index(self.state)
        self.state = states[(idx + 1) % 3]
        if self.state == "hotspot":
            subprocess.run(["nmcli", "dev", "wifi", "hotspot", "ifname", "wlan0", "ssid", self.ssid, "password", "voiceai123"])
        elif self.state == "offline":
            subprocess.run(["nmcli", "radio", "wifi", "off"])
        else:
            subprocess.run(["nmcli", "radio", "wifi", "on"])
