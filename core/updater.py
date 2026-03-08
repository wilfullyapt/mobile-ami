import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from packaging import version
from hardware.power import get_battery
from hardware.network_manager import NetworkManager

logger = logging.getLogger(__name__)


class AutoUpdater:
    """
    Background daemon that checks for and applies OTA updates from GitHub tags.

    Update flow:
      1. Every check_interval seconds (default 30 min), when connected to WiFi
         with internet access and battery >= min_battery_pct:
      2. git fetch --tags origin
      3. Find the latest tag matching <channel>-* (e.g. "stable-1.2.3")
      4. If newer than current: git stash → git checkout <tag> → pip install
      5. Signal systemd to restart the service, then wait for .healthy to appear
      6. On health-check failure: roll back to previous tag + restart

    The .healthy sentinel is written by VoiceAssistant.__init__ via mark_as_healthy()
    once the new version boots cleanly.
    """

    def __init__(self, network: NetworkManager, config: dict):
        self.network = network
        cfg = config.get("auto_update", {})

        # Repo root: config override or auto-detect from this file's location
        repo_path_cfg = cfg.get("repo_path")
        if repo_path_cfg:
            self.repo_path = str(Path(repo_path_cfg).expanduser().resolve())
        else:
            self.repo_path = str(Path(__file__).resolve().parent.parent)

        self.enabled = cfg.get("enabled", True)
        self.channel = cfg.get("channel", "stable")
        self.check_interval = cfg.get("check_interval_sec", 1800)
        self.min_battery = cfg.get("min_battery_pct", 30)
        self.retries = cfg.get("health_check_retries", 3)

        self._previous_tag: str | None = None

        if self.enabled:
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def mark_as_healthy(self) -> None:
        """Called by VoiceAssistant on successful startup to signal the updater."""
        healthy = Path(self.repo_path) / ".healthy"
        healthy.write_text("ok")

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while True:
            time.sleep(self.check_interval)
            if self.network.state != "wifi" or not self.network.has_internet():
                logger.debug("AutoUpdater: skipping — no wifi/internet")
                continue
            bat, _ = get_battery()
            if bat < self.min_battery:
                logger.debug("AutoUpdater: skipping — battery %d%% < %d%%", bat, self.min_battery)
                continue
            self._try_update()

    # ------------------------------------------------------------------
    # Update logic
    # ------------------------------------------------------------------

    def _try_update(self) -> None:
        current = self._get_current_tag()
        latest = self._get_latest_tag()
        if latest is None:
            logger.debug("AutoUpdater: no tags found for channel '%s'", self.channel)
            return
        try:
            if version.parse(latest) <= version.parse(current):
                logger.debug("AutoUpdater: already up to date (%s)", current)
                return
        except Exception:
            if latest == current:
                return

        logger.info("AutoUpdater: update available %s → %s", current, latest)
        self._previous_tag = current
        try:
            self._perform_update(latest)
            if not self._health_check():
                logger.warning("AutoUpdater: health check failed — rolling back")
                self._rollback()
        except Exception as exc:
            logger.error("AutoUpdater: update error (%s) — rolling back", exc)
            self._rollback()

    def _get_current_tag(self) -> str:
        r = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        return r.stdout.strip() if r.returncode == 0 else "0.0.0"

    def _get_latest_tag(self) -> str | None:
        subprocess.run(
            ["git", "fetch", "--tags", "origin"],
            cwd=self.repo_path,
            capture_output=True,
        )
        r = subprocess.run(
            ["git", "tag", "-l", f"{self.channel}-*", "--sort=-version:refname"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        tags = [t.strip() for t in r.stdout.splitlines() if t.strip()]
        return tags[0] if tags else None

    def _perform_update(self, tag: str) -> None:
        logger.info("AutoUpdater: applying update to %s", tag)
        subprocess.run(["git", "stash"], cwd=self.repo_path, check=True, capture_output=True)
        subprocess.run(["git", "checkout", tag], cwd=self.repo_path, check=True, capture_output=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
            cwd=self.repo_path,
            check=True,
        )
        subprocess.run(["sudo", "systemctl", "restart", "amini.service"])

    def _health_check(self) -> bool:
        """
        Wait for .healthy to appear (written by VoiceAssistant.__init__ in the
        newly restarted process). Poll every 3 s up to retries * 20 times.
        """
        healthy = Path(self.repo_path) / ".healthy"
        try:
            healthy.unlink(missing_ok=True)
        except OSError:
            pass
        polls = self.retries * 20
        for _ in range(polls):
            if healthy.exists():
                logger.info("AutoUpdater: health check passed")
                return True
            time.sleep(3)
        logger.warning("AutoUpdater: health check timed out after %d s", polls * 3)
        return False

    def _rollback(self) -> None:
        if not self._previous_tag:
            logger.error("AutoUpdater: no previous tag — cannot roll back")
            return
        logger.info("AutoUpdater: rolling back to %s", self._previous_tag)
        subprocess.run(
            ["git", "checkout", self._previous_tag],
            cwd=self.repo_path,
            capture_output=True,
        )
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
            cwd=self.repo_path,
        )
        subprocess.run(["sudo", "systemctl", "restart", "amini.service"])
