"""
Core test suite runner routes.

Runs the project's own pytest suite (tests/) asynchronously.
Plugin-specific tests are handled in routes/plugins.py.

Endpoints:
  POST /api/test/run              — run full suite → job_id
  POST /api/test/run?agent=<slug> — run a specific installed agent's tests → job_id
  GET  /api/test/jobs/<job_id>    — poll job status / output
  GET  /api/test/jobs             — list all test jobs (most recent last)
"""

import logging
import subprocess
import sys
from pathlib import Path

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("test_runner", __name__)

# Absolute path to the project root (one level above core/)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _jobs():
    from flask import current_app
    return current_app.config["JOB_MANAGER"]


def _paths():
    from flask import current_app
    return current_app.config["VOICE_ASSISTANT"].paths


@bp.route("/api/test/run", methods=["POST"])
def api_test_run():
    """
    Start an async test run.
    Optional query param: agent=<slug> limits the run to that plugin's tests.
    Returns {"job_id": "...", "status": "running"} immediately.
    """
    agent = (request.args.get("agent") or "").strip()

    if agent:
        agent_tests_dir = _paths().agent_dir(agent) / "tests"
        if not _paths().agent_dir(agent).exists():
            return jsonify({"error": f"Agent '{agent}' not found"}), 404

        def _do_agent_tests() -> str:
            if not agent_tests_dir.exists():
                return f"No tests/ directory for agent '{agent}'."
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(agent_tests_dir), "-v", "--tb=short"],
                capture_output=True,
                text=True,
                cwd=str(_PROJECT_ROOT),
            )
            return result.stdout + (("\n" + result.stderr) if result.stderr.strip() else "")

        job_id = _jobs().start(_do_agent_tests, label=f"tests:agent:{agent}")
    else:
        def _do_full_tests() -> str:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
                capture_output=True,
                text=True,
                cwd=str(_PROJECT_ROOT),
            )
            return result.stdout + (("\n" + result.stderr) if result.stderr.strip() else "")

        job_id = _jobs().start(_do_full_tests, label="tests:full-suite")

    return jsonify({"job_id": job_id, "status": "running"}), 202


@bp.route("/api/test/jobs/<job_id>")
def api_test_job_status(job_id: str):
    job = _jobs().get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@bp.route("/api/test/jobs")
def api_test_jobs_list():
    all_jobs = [j for j in _jobs().list_all() if j.get("label", "").startswith("tests:")]
    return jsonify({"jobs": all_jobs})
