from typing import Any, Optional
from core.model_registry import ModelRegistry, ModelRole, ModelSpec, Backend


def _build_instance(spec: ModelSpec) -> Any:
    """
    Factory: the single place that constructs each model type.
    Imports are local so uninstalled libraries don't break module import.
    Returns the typed wrapper class for each role so the rest of the
    codebase works against stable interfaces rather than raw model objects.
    """
    if spec.role == ModelRole.STT:
        from core.sst import STT
        return STT(spec)

    if spec.role == ModelRole.TTS:
        from core.tts import TTS
        return TTS(spec)

    if spec.role == ModelRole.LLM:
        from core.llm import LLM
        return LLM(spec)

    if spec.role == ModelRole.WAKE:
        from core.wake_detector import WakeDetector
        return WakeDetector(spec)

    if spec.role == ModelRole.VAD:
        from core.vad import VAD
        return VAD(spec)

    if spec.role == ModelRole.SPEAKER:
        from core.speaker_encoder import SpeakerEncoder
        return SpeakerEncoder(spec)

    raise ValueError(f"Unknown model role: {spec.role}")


class ModelOrchestrator:
    """
    Central lifecycle manager for all AI/ML models.

    - Lazy-loads models on first get()
    - Enforces single Hailo-10H slot (one Hailo model at a time)
    - Supports hot-swapping via swap()
    - Preloads eager models at startup via preload_eager()
    """

    def __init__(self, registry: ModelRegistry):
        self._registry = registry
        self._instances: dict[ModelRole, Any] = {}
        self._hailo_slot_taken: bool = False

    def get(self, role: ModelRole) -> Any:
        """Return the loaded model instance, loading lazily if needed."""
        if role not in self._instances:
            self._load(role)
        return self._instances[role]

    def has(self, role: ModelRole) -> bool:
        """Return True if the registry has a spec for the given role."""
        try:
            self._registry.get(role)
            return True
        except KeyError:
            return False

    def swap(self, role: ModelRole, new_name: str, new_path: Optional[str] = None):
        """
        Hot-swap a model: unload the current instance, update the registry,
        and let the next get() reload lazily.
        """
        self._unload(role)
        self._registry.override(role, new_name, new_path)

    def preload_eager(self):
        """Load all specs marked eager=True. Call once at startup."""
        for spec in self._registry.all_specs():
            if spec.eager:
                self._load(spec.role)

    def shutdown(self):
        """Cleanly unload all models."""
        for role in list(self._instances.keys()):
            self._unload(role)

    def _load(self, role: ModelRole):
        spec = self._registry.get(role)
        if spec.backend == Backend.HAILO:
            if self._hailo_slot_taken:
                raise RuntimeError(
                    f"Cannot load {role} on Hailo: device already assigned to another model. "
                    "Swap the current Hailo model first."
                )
            self._hailo_slot_taken = True
        self._instances[role] = _build_instance(spec)

    def _unload(self, role: ModelRole):
        inst = self._instances.pop(role, None)
        if inst is None:
            return
        spec = self._registry.get(role)
        if spec.backend == Backend.HAILO:
            self._hailo_slot_taken = False
        if hasattr(inst, "close"):
            inst.close()
        elif hasattr(inst, "shutdown"):
            inst.shutdown()
