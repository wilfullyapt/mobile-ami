"""
SystemPromptManager — manages ally_system.md, the base instruction layer.

Located at ~/.amini/ally_system.md.
Created from the committed ally_system.md.default template on first use,
following the same pattern as config.yaml / config.yaml.default.

The base layer defines device-level persona: who Ami is, how she speaks,
and when she speaks unprompted. It is intentionally separate from soul.md
(owner-specific identity and memories) so the device persona can evolve
independently from the owner relationship.

At runtime, both layers are merged in BaseAllyAgent.build_system_prompt():
    base = system_prompt_manager.read()       # ally_system.md
    soul = soul_manager.read(has_owner=...)   # soul.md
    merged = base.replace("{{SOUL}}", soul)   # injected at the {{SOUL}} marker

Usage::

    mgr = SystemPromptManager(paths, project_root=Path("/home/pi/mobile-ami"))
    mgr.ensure()           # copy .default → ~/.amini/ally_system.md if absent
    content = mgr.read()   # for system prompt injection
    mgr.write_raw("...")   # for user edits via web UI or CLI
"""

import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.ami_paths import AmiPaths

logger = logging.getLogger(__name__)


class SystemPromptManager:
    """
    Reads and writes the ally_system.md base instruction layer.

    Parameters
    ----------
    paths:
        AmiPaths instance — provides ally_system_path (``~/.amini/ally_system.md``).
    project_root:
        Optional path to the project source root. Used to locate
        ``ally_system.md.default``. If None, fallback to the file next to
        this module's package root.
    """

    def __init__(self, paths: "AmiPaths", project_root: Optional[Path] = None):
        self._path = paths.ally_system_path
        # Locate the .default template
        if project_root is not None:
            self._default: Optional[Path] = project_root / "ally_system.md.default"
        else:
            # Best-effort: walk up from this file to find the project root
            here = Path(__file__).resolve()
            candidate = here.parent.parent.parent / "ally_system.md.default"
            self._default = candidate if candidate.exists() else None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def ensure(self) -> None:
        """
        Copy ally_system.md.default → ~/.amini/ally_system.md if not present.

        Called during owner establishment and on first ``amini run``, mirroring
        ConfigManager.ensure_config() for config.yaml.
        """
        if self._path.exists():
            return
        if self._default and self._default.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(self._default.read_text())
            logger.info("SystemPromptManager: created ally_system.md from default")
        else:
            logger.warning(
                "SystemPromptManager: default template not found at %s; "
                "ally_system.md will be empty until manually populated.",
                self._default,
            )

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def read(self) -> str:
        """
        Return the current ally_system.md content.

        Falls back to the .default template if the user copy does not exist yet,
        so the system works correctly before ``ensure()`` has been called.
        """
        if self._path.exists():
            try:
                return self._path.read_text()
            except OSError as exc:
                logger.warning("SystemPromptManager: could not read ally_system.md: %s", exc)
        if self._default and self._default.exists():
            try:
                return self._default.read_text()
            except OSError:
                pass
        return ""

    def exists(self) -> bool:
        """True if the user-local ally_system.md file exists."""
        return self._path.exists()

    def write_raw(self, content: str) -> None:
        """
        Overwrite ally_system.md with arbitrary content.

        Used by the web UI and CLI to let users customise the device persona.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(content)
        logger.info("SystemPromptManager: ally_system.md updated (%d chars)", len(content))

    def reset_to_default(self) -> bool:
        """
        Overwrite the user copy with the committed .default template.

        Returns True if the reset succeeded, False if no default is available.
        """
        if not (self._default and self._default.exists()):
            logger.warning("SystemPromptManager: no default template found for reset")
            return False
        self.write_raw(self._default.read_text())
        logger.info("SystemPromptManager: ally_system.md reset to default")
        return True
