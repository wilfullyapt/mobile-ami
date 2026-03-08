"""Unit tests for core/model_registry.py"""

import pytest
from unittest.mock import MagicMock
from core.model_registry import (
    Backend,
    ModelRegistry,
    ModelRole,
    ModelSpec,
    QuantType,
)


SAMPLE_CONFIG = {
    "stt": {
        "name": "tiny",
        "backend": "cpu",
        "quant": "int8",
        "path": None,
        "version": "tiny",
        "eager": False,
    },
    "tts": {
        "name": "en_US-lessac-medium",
        "backend": "cpu",
        "quant": "none",
        "path": "/opt/piper/en_US-lessac-medium.onnx",
        "version": "medium",
        "eager": False,
    },
    "llm": {
        "name": "llama3.2:1b",
        "backend": "cpu",
        "quant": "none",
        "path": None,
        "version": "1b",
        "eager": False,
    },
    "wake": {
        "name": "hey_assistant",
        "backend": "cpu",
        "quant": "none",
        "path": None,
        "version": "hey_assistant",
        "eager": True,
    },
    "vad": {
        "name": "webrtcvad",
        "backend": "cpu",
        "quant": "none",
        "path": None,
        "version": "2",
        "eager": True,
    },
}


class TestEnums:
    def test_backend_values(self):
        assert Backend.CPU == "cpu"
        assert Backend.HAILO == "hailo"

    def test_backend_from_string(self):
        assert Backend("cpu") == Backend.CPU
        assert Backend("hailo") == Backend.HAILO

    def test_quant_values(self):
        assert QuantType.INT8 == "int8"
        assert QuantType.FLOAT16 == "float16"
        assert QuantType.NONE == "none"

    def test_model_role_values(self):
        assert ModelRole.STT == "stt"
        assert ModelRole.TTS == "tts"
        assert ModelRole.LLM == "llm"
        assert ModelRole.WAKE == "wake"
        assert ModelRole.VAD == "vad"


class TestModelSpec:
    def test_fields(self):
        spec = ModelSpec(
            role=ModelRole.STT,
            name="tiny",
            backend=Backend.CPU,
            quant=QuantType.INT8,
            path=None,
            version="tiny",
        )
        assert spec.role == ModelRole.STT
        assert spec.name == "tiny"
        assert spec.backend == Backend.CPU
        assert spec.quant == QuantType.INT8
        assert spec.path is None
        assert spec.version == "tiny"
        assert spec.eager is False

    def test_eager_default(self):
        spec = ModelSpec(
            role=ModelRole.VAD,
            name="webrtcvad",
            backend=Backend.CPU,
            quant=QuantType.NONE,
            path=None,
            version="2",
        )
        assert spec.eager is False

    def test_eager_explicit(self):
        spec = ModelSpec(
            role=ModelRole.WAKE,
            name="hey_assistant",
            backend=Backend.CPU,
            quant=QuantType.NONE,
            path=None,
            version="hey_assistant",
            eager=True,
        )
        assert spec.eager is True


class TestModelRegistry:
    def setup_method(self):
        self.registry = ModelRegistry(SAMPLE_CONFIG)

    def test_get_stt(self):
        spec = self.registry.get(ModelRole.STT)
        assert spec.name == "tiny"
        assert spec.backend == Backend.CPU
        assert spec.quant == QuantType.INT8
        assert spec.eager is False

    def test_get_tts(self):
        spec = self.registry.get(ModelRole.TTS)
        assert spec.path == "/opt/piper/en_US-lessac-medium.onnx"
        assert spec.quant == QuantType.NONE

    def test_get_wake_is_eager(self):
        spec = self.registry.get(ModelRole.WAKE)
        assert spec.eager is True

    def test_get_vad_is_eager(self):
        spec = self.registry.get(ModelRole.VAD)
        assert spec.eager is True

    def test_get_missing_role_raises(self):
        # Remove stt from config and create a new registry
        cfg = {k: v for k, v in SAMPLE_CONFIG.items() if k != "stt"}
        registry = ModelRegistry(cfg)
        with pytest.raises(KeyError):
            registry.get(ModelRole.STT)

    def test_all_specs_returns_all(self):
        specs = self.registry.all_specs()
        roles = {s.role for s in specs}
        assert roles == {ModelRole.STT, ModelRole.TTS, ModelRole.LLM, ModelRole.WAKE, ModelRole.VAD}

    def test_override_name(self):
        self.registry.override(ModelRole.STT, "small")
        spec = self.registry.get(ModelRole.STT)
        assert spec.name == "small"
        assert spec.version == "small"
        # backend/quant/eager unchanged
        assert spec.backend == Backend.CPU
        assert spec.quant == QuantType.INT8
        assert spec.eager is False

    def test_override_name_and_path(self):
        self.registry.override(ModelRole.TTS, "en_US-ryan-medium", "/opt/piper/ryan.onnx")
        spec = self.registry.get(ModelRole.TTS)
        assert spec.name == "en_US-ryan-medium"
        assert spec.path == "/opt/piper/ryan.onnx"

    def test_override_path_none_preserves_existing(self):
        original_path = self.registry.get(ModelRole.TTS).path
        self.registry.override(ModelRole.TTS, "new-model")
        # path=None in override → keeps existing path
        spec = self.registry.get(ModelRole.TTS)
        assert spec.path == original_path

    def test_llm_version_string(self):
        spec = self.registry.get(ModelRole.LLM)
        assert spec.version == "1b"

    def test_defaults_applied_when_fields_omitted(self):
        minimal_config = {
            "stt": {"name": "tiny"},
        }
        registry = ModelRegistry(minimal_config)
        spec = registry.get(ModelRole.STT)
        assert spec.backend == Backend.CPU
        assert spec.quant == QuantType.NONE
        assert spec.path is None
        assert spec.eager is False
        assert spec.version == "tiny"


# ---------------------------------------------------------------------------
# TestModelRegistryWithPaths — AmiPaths integration
# ---------------------------------------------------------------------------

class TestModelRegistryWithPaths:
    """Verify that ModelRegistry resolves paths via AmiPaths when provided."""

    def _make_paths(self, tmp_path):
        from core.ami_paths import AmiPaths
        p = AmiPaths(root=str(tmp_path / "amini"))
        p.ensure_dirs()
        return p

    def test_null_path_resolves_to_model_dir(self, tmp_path):
        paths = self._make_paths(tmp_path)
        cfg = {"stt": {"name": "tiny", "path": None}}
        registry = ModelRegistry(cfg, paths)
        spec = registry.get(ModelRole.STT)
        assert spec.path == str(paths.model_dir("stt"))

    def test_bare_filename_resolves_under_role_dir(self, tmp_path):
        paths = self._make_paths(tmp_path)
        cfg = {"tts": {"name": "en_US-lessac-medium", "path": "en_US-lessac-medium.onnx"}}
        registry = ModelRegistry(cfg, paths)
        spec = registry.get(ModelRole.TTS)
        assert spec.path == str(paths.model_dir("tts") / "en_US-lessac-medium.onnx")

    def test_absolute_path_preserved(self, tmp_path):
        paths = self._make_paths(tmp_path)
        cfg = {"tts": {"name": "en_US-lessac-medium", "path": "/abs/path/model.onnx"}}
        registry = ModelRegistry(cfg, paths)
        spec = registry.get(ModelRole.TTS)
        assert spec.path == "/abs/path/model.onnx"

    def test_no_paths_arg_preserves_original_behaviour(self):
        """Existing tests pass no paths — path from config returned as-is."""
        cfg = {"tts": {"name": "en_US-lessac-medium", "path": "/opt/piper/model.onnx"}}
        registry = ModelRegistry(cfg)
        spec = registry.get(ModelRole.TTS)
        assert spec.path == "/opt/piper/model.onnx"

    def test_no_paths_null_path_stays_none(self):
        cfg = {"stt": {"name": "tiny", "path": None}}
        registry = ModelRegistry(cfg)
        spec = registry.get(ModelRole.STT)
        assert spec.path is None

    def test_all_roles_get_distinct_dirs(self, tmp_path):
        paths = self._make_paths(tmp_path)
        cfg = {role: {"name": role, "path": None} for role in ("stt", "tts", "llm", "wake", "vad")}
        registry = ModelRegistry(cfg, paths)
        resolved = [registry.get(ModelRole(r)).path for r in ("stt", "tts", "llm", "wake", "vad")]
        # All paths are distinct
        assert len(set(resolved)) == len(resolved)
