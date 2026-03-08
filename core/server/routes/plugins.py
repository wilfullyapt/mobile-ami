"""
3rd-party plugin management routes.

All install/test operations are async (background thread); the client
polls /api/plugins/jobs/<job_id> for completion.

Endpoints:
  GET  /api/plugins                      — list installed plugins (manifest data)
  POST /api/plugins/install              — install from GitHub {source: "user/repo"}
  DELETE /api/plugins/<name>             — uninstall a plugin
  POST /api/plugins/<name>/test          — run a plugin's tests → job_id
  GET  /api/plugins/jobs/<job_id>        — poll async job status
"""

import json
import logging
import subprocess
import sys

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("plugins", __name__)


def _ctx():
    from flask import current_app
    return current_app.config


def _installer():
    return _ctx()["ADDON_INSTALLER"]


def _jobs():
    return _ctx()["JOB_MANAGER"]


def _paths():
    return _ctx()["VOICE_ASSISTANT"].paths


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _read_manifest(name: str) -> dict:
    manifest_path = _paths().agent_manifest(name)
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _list_installed() -> list[dict]:
    agents = []
    for name in _paths().list_agents():
        manifest = _read_manifest(name)
        agents.append({
            "name": name,
            "version": manifest.get("version", "unknown"),
            "entry_class": manifest.get("entry_class", ""),
            "description": manifest.get("description", ""),
        })
    return agents


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@bp.route("/api/plugins")
def api_plugins_list():
    try:
        return jsonify({"plugins": _list_installed()})
    except Exception as exc:
        logger.error("GET /api/plugins failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/plugins/install", methods=["POST"])
def api_plugins_install():
    """Start an async install job. Returns job_id immediately."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        source = (data.get("source") or "").strip()
        if not source:
            return jsonify({"error": "source is required (e.g. user/repo)"}), 400

        installer = _installer()

        def _do_install() -> str:
            name = installer.install(source)
            return f"Installed agent '{name}' successfully."

        job_id = _jobs().start(_do_install, label=f"install:{source}")
        return jsonify({"job_id": job_id, "status": "running"}), 202
    except Exception as exc:
        logger.error("POST /api/plugins/install failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/plugins/<name>", methods=["DELETE"])
def api_plugins_remove(name: str):
    try:
        _installer().uninstall(name)
        return jsonify({"ok": True, "removed": name})
    except FileNotFoundError:
        return jsonify({"error": f"Plugin '{name}' not found"}), 404
    except Exception as exc:
        logger.error("DELETE /api/plugins/%s failed: %s", name, exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/plugins/<name>/test", methods=["POST"])
def api_plugins_test(name: str):
    """Run a plugin's test suite asynchronously. Returns job_id."""
    try:
        paths = _paths()
        tests_dir = paths.agent_dir(name) / "tests"
        if not paths.agent_dir(name).exists():
            return jsonify({"error": f"Plugin '{name}' not found"}), 404

        def _do_test() -> str:
            if not tests_dir.exists():
                return "No tests directory found for this plugin."
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(tests_dir), "-v", "--tb=short"],
                capture_output=True,
                text=True,
            )
            combined = result.stdout + (("\n" + result.stderr) if result.stderr.strip() else "")
            return combined

        job_id = _jobs().start(_do_test, label=f"test-plugin:{name}")
        return jsonify({"job_id": job_id, "status": "running"}), 202
    except Exception as exc:
        logger.error("POST /api/plugins/%s/test failed: %s", name, exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/plugins/jobs/<job_id>")
def api_plugins_job_status(job_id: str):
    job = _jobs().get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)
