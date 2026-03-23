import json
import os
import tempfile
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

    @property
    def conversations_dir(self) -> Path:
        return self._root / "conversations"

    def conversation_agent_dir(self, agent: str) -> Path:
        """~/.amini/conversations/<agent>/"""
        return self.conversations_dir / agent

    @property
    def profiles_dir(self) -> Path:
        """~/.amini/profiles/ — voice profile metadata and embeddings."""
        return self._root / "profiles"

    @property
    def data_dir(self) -> Path:
        """~/.amini/data/ — shared family data: calendar, shopping list, messages."""
        return self._root / "data"

    def message_dir(self, name: str) -> Path:
        """~/.amini/data/messages/<name>/ — per-person voice message inbox."""
        return self.data_dir / "messages" / name

    def agent_data_dir(self, slug: str) -> Path:
        """~/.amini/data/<slug>/ — per-agent private data directory."""
        return self.data_dir / slug

    @property
    def ally_notes_dir(self) -> Path:
        """~/.amini/data/ally/notes/ — AmbientNote JSON files."""
        return self.agent_data_dir("ally") / "notes"

    @property
    def ally_audio_dir(self) -> Path:
        """~/.amini/data/ally/audio/ — unknown voice WAV clips."""
        return self.agent_data_dir("ally") / "audio"

    @property
    def ally_memory_dir(self) -> Path:
        """~/.amini/data/ally/memory/ — ally-written dated memory entries."""
        return self.agent_data_dir("ally") / "memory"

    # ------------------------------------------------------------------
    # Ally / owner / soul paths
    # ------------------------------------------------------------------

    @property
    def soul_path(self) -> Path:
        """~/.amini/soul.md — the ally agent's identity and purpose file."""
        return self._root / "soul.md"

    @property
    def ally_system_path(self) -> Path:
        """~/.amini/ally_system.md — the base persona/instruction layer for ally agents."""
        return self._root / "ally_system.md"

    @property
    def owner_path(self) -> Path:
        """~/.amini/owner.json — device owner identity and last-seen timestamp."""
        return self._root / "owner.json"

    @property
    def memory_dir(self) -> Path:
        """~/.amini/memory/ — per-day LLM summaries from eval_day."""
        return self._root / "memory"

    @property
    def eval_marker_path(self) -> Path:
        """~/.amini/.last_eval — ISO timestamp of last completed eval_day run."""
        return self._root / ".last_eval"

    def ensure_dirs(self) -> None:
        """Create the full directory tree under ~/.amini/ if not already present."""
        for role in ("stt", "tts", "wake", "llm", "hailo", "speaker"):
            (self.models_dir / role).mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        (self.profiles_dir / "embeddings").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "messages").mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.ally_notes_dir.mkdir(parents=True, exist_ok=True)
        self.ally_audio_dir.mkdir(parents=True, exist_ok=True)
        self.ally_memory_dir.mkdir(parents=True, exist_ok=True)

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
    # Persistent settings
    # ------------------------------------------------------------------

    @property
    def settings_path(self) -> Path:
        """~/.amini/settings.json"""
        return self._root / "settings.json"

    def load_settings(self) -> dict:
        """Load settings from ~/.amini/settings.json; return {} if missing or invalid."""
        if not self.settings_path.exists():
            return {}
        try:
            return json.loads(self.settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def save_settings(self, data: dict) -> None:
        """Atomically write settings to ~/.amini/settings.json."""
        self._root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.settings_path)
        except Exception:
            os.unlink(tmp)
            raise

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
