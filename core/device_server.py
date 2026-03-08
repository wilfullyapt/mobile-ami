import logging
import threading

from flask import Flask, jsonify, request

logger = logging.getLogger(__name__)

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Amini Device</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen p-4">
<div class="max-w-md mx-auto space-y-4">

  <h1 class="text-2xl font-bold text-center text-indigo-400">Amini Device</h1>

  <!-- Status card -->
  <div class="bg-gray-800 rounded-xl p-4 space-y-2" id="status-card">
    <div class="flex justify-between">
      <span class="text-gray-400">Battery</span>
      <span id="battery">--</span>
    </div>
    <div class="flex justify-between">
      <span class="text-gray-400">Network</span>
      <span id="network">--</span>
    </div>
    <div class="flex justify-between">
      <span class="text-gray-400">Internet</span>
      <span id="internet">--</span>
    </div>
    <div class="flex justify-between">
      <span class="text-gray-400">Agent</span>
      <span id="agent" class="font-semibold text-indigo-300">--</span>
    </div>
  </div>

  <!-- Agent controls -->
  <div class="bg-gray-800 rounded-xl p-4 space-y-3">
    <h2 class="font-semibold text-gray-300">Agent</h2>
    <div id="agent-list" class="space-y-2"></div>
    <button onclick="cycleAgent()"
      class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-2 rounded-lg">
      Cycle Agent
    </button>
  </div>

  <!-- Settings -->
  <div class="bg-gray-800 rounded-xl p-4 space-y-3">
    <h2 class="font-semibold text-gray-300">Settings</h2>
    <label class="flex items-center justify-between cursor-pointer">
      <span class="text-gray-400">Hotword Trigger</span>
      <input type="checkbox" id="hotword-toggle" onchange="updateHotword(this.checked)"
        class="w-5 h-5 accent-indigo-500">
    </label>
  </div>

  <!-- Network controls -->
  <div class="bg-gray-800 rounded-xl p-4 space-y-2">
    <h2 class="font-semibold text-gray-300">Network</h2>
    <div class="flex justify-between text-sm">
      <span class="text-gray-400">State</span><span id="net-state">--</span>
    </div>
    <div class="flex justify-between text-sm">
      <span class="text-gray-400">SSID</span><span id="net-ssid">--</span>
    </div>
    <div class="flex justify-between text-sm">
      <span class="text-gray-400">IP</span><span id="net-ip">--</span>
    </div>
    <button onclick="cycleNetwork()"
      class="w-full bg-gray-600 hover:bg-gray-500 text-white font-semibold py-2 rounded-lg">
      Cycle Network Mode
    </button>
  </div>

</div>

<script>
async function fetchStatus() {
  const r = await fetch('/api/status');
  const s = await r.json();
  document.getElementById('battery').textContent = s.battery_pct + '% ' + s.voltage + 'V';
  document.getElementById('network').textContent = s.net_state;
  document.getElementById('internet').textContent = s.has_internet ? '✓ Online' : '✗ Offline';
  document.getElementById('agent').textContent = s.agent;
  document.getElementById('hotword-toggle').checked = s.hotword_trigger;

  const list = document.getElementById('agent-list');
  list.innerHTML = '';
  (s.agents || []).forEach(slug => {
    const active = slug === s.agent;
    const btn = document.createElement('button');
    btn.textContent = slug;
    btn.className = 'w-full py-1 rounded-lg text-sm font-medium ' +
      (active ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600');
    btn.onclick = () => setAgent(slug);
    list.appendChild(btn);
  });
}

async function fetchNetwork() {
  const r = await fetch('/api/network');
  const n = await r.json();
  document.getElementById('net-state').textContent = n.state;
  document.getElementById('net-ssid').textContent = n.ssid || '--';
  document.getElementById('net-ip').textContent = n.ip || '--';
}

async function cycleAgent() {
  await fetch('/api/agent/cycle', {method: 'POST'});
  fetchStatus();
}

async function setAgent(slug) {
  await fetch('/api/agent/set/' + slug, {method: 'POST'});
  fetchStatus();
}

async function updateHotword(value) {
  await fetch('/api/settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({hotword_trigger: value})
  });
}

async function cycleNetwork() {
  await fetch('/api/network/cycle', {method: 'POST'});
  fetchNetwork();
}

fetchStatus();
fetchNetwork();
setInterval(() => { fetchStatus(); fetchNetwork(); }, 10000);
</script>
</body>
</html>"""


class DeviceServer:
    """
    Lightweight Flask HTTP server for device management.

    Starts automatically when network state is 'hotspot' or 'wifi';
    runs as a daemon thread so it never blocks the voice loop.

    All routes share a reference to VoiceAssistant for live state access.
    """

    def __init__(self, port: int, voice_assistant):
        self._port = port
        self._va = voice_assistant
        self._app = self._build_app()
        self._thread: threading.Thread | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        logger.info("DeviceServer started on port %d", self._port)

    def stop(self) -> None:
        # The daemon thread exits when the process exits; Flask's dev server
        # doesn't support a clean shutdown from another thread without additional
        # machinery. We mark the flag so start() won't restart needlessly.
        self._running = False
        logger.info("DeviceServer stopped (daemon thread will idle)")

    def _serve(self) -> None:
        self._app.run(host="0.0.0.0", port=self._port, use_reloader=False)

    # ------------------------------------------------------------------
    # Route construction
    # ------------------------------------------------------------------

    def _build_app(self) -> Flask:
        app = Flask(__name__)
        # Silence Flask's default request logger to keep amini logs clean
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.WARNING)

        va = self._va

        @app.route("/")
        def dashboard():
            return _DASHBOARD_HTML, 200, {"Content-Type": "text/html"}

        @app.route("/api/status")
        def api_status():
            return jsonify(va.get_status())

        @app.route("/api/agent/cycle", methods=["POST"])
        def api_agent_cycle():
            va.cycle_agent()
            return jsonify({"agent": va.agent_manager.current})

        @app.route("/api/agent/set/<slug>", methods=["POST"])
        def api_agent_set(slug: str):
            slugs = va.agent_manager._slugs
            if slug not in slugs:
                return jsonify({"error": f"Unknown agent: {slug}"}), 404
            va.agent_manager._index = slugs.index(slug)
            va.display.update_mode(slug)
            return jsonify({"agent": slug})

        @app.route("/api/agents")
        def api_agents():
            return jsonify({"agents": va.agent_manager._slugs})

        @app.route("/api/settings", methods=["GET"])
        def api_settings_get():
            return jsonify(va._settings)

        @app.route("/api/settings", methods=["POST"])
        def api_settings_post():
            data = request.get_json(force=True, silent=True) or {}
            for key, value in data.items():
                va.update_setting(key, value)
            return jsonify(va._settings)

        @app.route("/api/network")
        def api_network():
            return jsonify({
                "state": va.network.state,
                "ssid": va.network.ssid,
                "ip": va.network.get_device_ip(),
                "has_internet": va.network.has_internet(),
            })

        @app.route("/api/network/cycle", methods=["POST"])
        def api_network_cycle():
            va.network.cycle_state()
            return jsonify({"state": va.network.state})

        return app
