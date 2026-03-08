import dataclasses
import os
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.ami_paths import AmiPaths


class Backend(str, Enum):
    CPU = "cpu"
    HAILO = "hailo"


class QuantType(str, Enum):
    INT8 = "int8"
    FLOAT16 = "float16"
    NONE = "none"


class ModelRole(str, Enum):
    STT = "stt"
    TTS = "tts"
    LLM = "llm"
    WAKE = "wake"
    VAD = "vad"


@dataclass
class ModelSpec:
    role: ModelRole
    name: str            # ollama model tag, whisper size, oww wakeword, etc.
    backend: Backend
    quant: QuantType
    path: Optional[str]  # absolute path for file-based models; None for runtime-managed
    version: str         # descriptive version string
    eager: bool = False  # if True, load at startup rather than lazily


class ModelRegistry:
    """
    Pure data layer. Reads model definitions from config and exposes typed ModelSpec objects.
    No loading or I/O beyond config parsing.

    When an AmiPaths instance is provided, model paths are resolved relative to
    ~/.amini/models/<role>/ so all model data lives in the user's home directory.
    Without paths (or for absolute/~ paths in config), behaviour is unchanged.
    """

    def __init__(self, models_config: dict, paths: "Optional[AmiPaths]" = None):
        self._specs: dict[ModelRole, ModelSpec] = {}
        for role_str, cfg in models_config.items():
            role = ModelRole(role_str)
            spec = ModelSpec(
                role=role,
                name=cfg["name"],
                backend=Backend(cfg.get("backend", "cpu")),
                quant=QuantType(cfg.get("quant", "none")),
                path=cfg.get("path"),
                version=str(cfg.get("version", cfg["name"])),
                eager=cfg.get("eager", False),
            )
            if paths is not None:
                spec = dataclasses.replace(
                    spec,
                    path=paths.resolve_model_path(role_str, spec.path),
                )
            elif spec.path:
                spec = dataclasses.replace(spec, path=os.path.expanduser(spec.path))
            self._specs[role] = spec

    def get(self, role: ModelRole) -> ModelSpec:
        if role not in self._specs:
            raise KeyError(f"No model spec registered for role: {role}")
        return self._specs[role]

    def all_specs(self) -> list[ModelSpec]:
        return list(self._specs.values())

    def override(self, role: ModelRole, name: str, path: Optional[str] = None):
        """Replace name (and optionally path) for a role. Used by orchestrator.swap()."""
        spec = self._specs[role]
        self._specs[role] = ModelSpec(
            role=spec.role,
            name=name,
            backend=spec.backend,
            quant=spec.quant,
            path=path if path is not None else spec.path,
            version=name,
            eager=spec.eager,
        )
