"""
Device server — Flask HTTP server for device management.

Architecture:
  - Flask app wired with blueprints for each feature area.
  - Served via werkzeug's WSGIServer for clean, thread-safe shutdown.
  - Static CSS and Jinja2 templates are served from core/server/.
  - Starts automatically when network state is 'hotspot' or 'wifi'.
  - Stops cleanly when returning to 'offline'.
  - All external state is passed via Flask app.config — no globals.
"""

import logging
import threading
from pathlib import Path

from flask import Flask, render_template

logger = logging.getLogger(__name__)

# Paths to the companion static/template directories
_SERVER_DIR = Path(__file__).parent  # already in core/server/
_TEMPLATE_DIR = _SERVER_DIR / "templates"
_STATIC_DIR = _SERVER_DIR / "static"


class DeviceServer:
    """
    Lifecycle-managed Flask HTTP server.

    Pass the VoiceAssistant, AddonInstaller, JobManager, and
    ConversationLogger at construction time; they are stored in
    Flask app.config and accessed by blueprints via current_app.
    """

    def __init__(
        self,
        port: int,
        voice_assistant,
        addon_installer=None,
        conv_logger=None,
        job_manager=None,
        config_manager=None,
    ):
        self._port = port
        self._app = self._build_app(voice_assistant, addon_installer, conv_logger, job_manager, config_manager)
        self._server = None          # werkzeug WSGIServer — set on start()
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
        self._running = False
        if self._server:
            self._server.shutdown()
            self._server = None
        logger.info("DeviceServer stopped")

    def _serve(self) -> None:
        from werkzeug.serving import make_server
        self._server = make_server("0.0.0.0", self._port, self._app)
        self._server.serve_forever()

    # ------------------------------------------------------------------
    # Flask app factory
    # ------------------------------------------------------------------

    def _build_app(self, va, installer, conv_logger, job_manager, config_manager=None) -> Flask:
        app = Flask(
            __name__,
            template_folder=str(_TEMPLATE_DIR),
            static_folder=str(_STATIC_DIR),
        )

        # Silence werkzeug request logs — amini's own logger is the authority
        logging.getLogger("werkzeug").setLevel(logging.WARNING)

        # ── Shared context stored in app.config ────────────────────────
        app.config["VOICE_ASSISTANT"] = va
        app.config["ADDON_INSTALLER"] = installer
        app.config["CONV_LOGGER"] = conv_logger
        app.config["JOB_MANAGER"] = job_manager
        app.config["CONFIG_MANAGER"] = config_manager

        # ── Dashboard ──────────────────────────────────────────────────
        @app.route("/")
        def dashboard():
            return render_template("index.html")

        # ── Blueprints ──────────────────────────────────────────────────
        from core.server.routes.status import bp as status_bp
        from core.server.routes.network import bp as network_bp
        from core.server.routes.plugins import bp as plugins_bp
        from core.server.routes.conversations import bp as conv_bp
        from core.server.routes.test_runner import bp as test_bp
        from core.server.routes.config import bp as config_bp

        for bp in (status_bp, network_bp, plugins_bp, conv_bp, test_bp, config_bp):
            app.register_blueprint(bp)

        # ── Generic error handlers ─────────────────────────────────────
        from flask import jsonify

        @app.errorhandler(404)
        def not_found(e):
            return jsonify({"error": "Not found"}), 404

        @app.errorhandler(405)
        def method_not_allowed(e):
            return jsonify({"error": "Method not allowed"}), 405

        @app.errorhandler(500)
        def internal_error(e):
            logger.error("Unhandled server error: %s", e)
            return jsonify({"error": "Internal server error"}), 500

        return app
