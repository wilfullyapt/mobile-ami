import os
from pathlib import Path


class AmiPaths:
    """
    File-system abstraction for the ~/.amini/ user data directory.

    All model storage, agent plugins, and runtime data live here —
    separate from the project source tree — so the user owns their AI stack.

    Default root: ~/.amini/
    Override root for testing: AmiPaths("/tmp/test-amini")
    """

    def __init__(self, root: str = "~/.amini"):
        self._root = Path(root).expanduser().resolve()

    # ------------------------------------------------------------------
    # Root
    # ------------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Model directories
    # ------------------------------------------------------------------

    @property
    def models_dir(self) -> Path:
        return self._root / "models"

    @property
    def agents_dir(self) -> Path:
        return self._root / "agents"

    def model_dir(self, role: str) -> Path:
        """~/.amini/models/<role>/"""
        return self.models_dir / role

    def agent_dir(self, name: str) -> Path:
        """~/.amini/agents/<name>/"""
        return self.agents_dir / name

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def ensure_dirs(self) -> None:
        """Create the full directory tree under ~/.amini/ if not already present."""
        for role in ("stt", "tts", "wake", "llm", "hailo"):
            (self.models_dir / role).mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Agent discovery
    # ------------------------------------------------------------------

    def list_agents(self) -> list[str]:
        """Return names of all installed plugin agents."""
        if not self.agents_dir.exists():
            return []
        return sorted(d.name for d in self.agents_dir.iterdir() if d.is_dir())

    def agent_manifest(self, name: str) -> Path:
        """~/.amini/agents/<name>/manifest.json"""
        return self.agent_dir(name) / "manifest.json"

    def agent_module(self, name: str) -> Path:
        """~/.amini/agents/<name>/agent.py"""
        return self.agent_dir(name) / "agent.py"

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def resolve_model_path(self, role: str, path_cfg: "str | None") -> "str | None":
        """
        Resolve a raw path value from config.yaml into an absolute path.

        Rules:
          None           → str(model_dir(role))          directory for runtime-managed models
          'file.onnx'    → model_dir(role) / 'file.onnx' bare filename relative to role dir
          '/abs/path'    → /abs/path                      already absolute, expand ~ only
          '~/path'       → expanded absolute path
        """
        if path_cfg is None:
            return str(self.model_dir(role))
        expanded = os.path.expanduser(path_cfg)
        if os.path.isabs(expanded):
            return expanded
        # bare filename or relative path → anchor to role's model dir
        return str(self.model_dir(role) / path_cfg)
