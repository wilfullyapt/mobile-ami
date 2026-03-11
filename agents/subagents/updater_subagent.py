"""
UpdaterSubAgent — plugin management tools.

Primary tool:    check_updates()
Additional tools: install_agent(repo), list_installed_agents()
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from agents.base_sub_agent import BaseSubAgent
from agents.tools.base_tool import BaseTool, ToolParam

if TYPE_CHECKING:
    from core.models.orchestrator import ModelOrchestrator
    from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)


class _InstallAgentTool(BaseTool):
    name = "install_agent"
    description = "Install a third-party agent plugin from a GitHub repository (user/repo)."
    parameters = [
        ToolParam("repo", "string", "GitHub repository in user/repo format", required=True),
    ]

    def __init__(self, installer):
        self._installer = installer

    def execute(self, repo: str) -> str:
        if self._installer is None:
            return "Installer unavailable."
        try:
            self._installer.install(repo)
            return f"Agent from {repo} installed successfully."
        except Exception as exc:  # noqa: BLE001
            logger.error("install_agent failed: %s", exc)
            return f"Failed to install {repo}: {exc}"


class _ListInstalledAgentsTool(BaseTool):
    name = "list_installed_agents"
    description = "List all installed third-party agent plugins."
    parameters = []

    def __init__(self, paths):
        self._paths = paths

    def execute(self) -> str:
        if self._paths is None:
            return "Paths unavailable."
        installed = self._paths.list_agents()
        if not installed:
            return "No third-party agents installed."
        return "Installed agents: " + ", ".join(installed)


class UpdaterSubAgent(BaseSubAgent):
    """Reports update availability and manages agent plugins."""

    name = "check_updates"
    description = "Check whether software updates are available for the device."
    parameters = []

    def __init__(
        self,
        orchestrator: "ModelOrchestrator",
        paths: "Optional[AmiPaths]" = None,
        installer=None,
    ):
        super().__init__(orchestrator, paths)
        self._installer = installer

    def execute(self) -> str:
        try:
            from core.updater import AutoUpdater
            # If we can import it, return a generic status — actual network
            # polling is async and happens in the background.
            return "Update check is managed automatically in the background. No manual action needed."
        except Exception as exc:  # noqa: BLE001
            logger.warning("check_updates: %s", exc)
            return "Update status unavailable."

    def get_additional_tools(self) -> list[BaseTool]:
        return [
            _InstallAgentTool(self._installer),
            _ListInstalledAgentsTool(self._paths),
        ]
