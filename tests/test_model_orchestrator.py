"""Unit tests for core/model_orchestrator.py"""

import pytest
from unittest.mock import MagicMock, patch, call

from core.model_registry import Backend, ModelRegistry, ModelRole, ModelSpec, QuantType
from core.model_orchestrator import ModelOrchestrator, _build_instance


EAGER_CONFIG = {
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
    "stt": {
        "name": "tiny",
        "backend": "cpu",
        "quant": "int8",
        "path": None,
        "version": "tiny",
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
    "tts": {
        "name": "en_US-lessac-medium",
        "backend": "cpu",
        "quant": "none",
        "path": None,
        "version": "medium",
        "eager": False,
    },
}

HAILO_CONFIG = {
    "stt": {
        "name": "whisper-tiny",
        "backend": "hailo",
        "quant": "int8",
        "path": "/opt/hailo/whisper-tiny.hef",
        "version": "tiny",
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
}


def _make_mock_instance():
    """Return a mock model instance."""
    inst = MagicMock()
    return inst


class TestBuildInstance:
    def test_build_stt(self):
        spec = ModelSpec(ModelRole.STT, "tiny", Backend.CPU, QuantType.INT8, None, "tiny")
        with patch("core.model_orchestrator.STT", create=True) as MockSTT:
            # Patch the import inside _build_instance
            with patch.dict("sys.modules", {"core.sst": MagicMock(STT=MockSTT)}):
                import importlib
                import core.model_orchestrator as mo
                importlib.reload(mo)
                mo._build_instance(spec)

    def test_unknown_role_raises(self):
        # Use a real ModelRole value but patch the if-chain by creating a fake spec
        spec = MagicMock()
        spec.role = "nonexistent_role"
        with pytest.raises((ValueError, AttributeError)):
            _build_instance(spec)


class TestModelOrchestratorLazyLoading:
    def setup_method(self):
        self.registry = ModelRegistry(EAGER_CONFIG)

    def test_get_loads_lazily(self):
        orch = ModelOrchestrator(self.registry)
        mock_inst = _make_mock_instance()
        with patch("core.model_orchestrator._build_instance", return_value=mock_inst) as mock_build:
            result = orch.get(ModelRole.STT)
            mock_build.assert_called_once()
            assert result is mock_inst

    def test_get_returns_cached_instance(self):
        orch = ModelOrchestrator(self.registry)
        mock_inst = _make_mock_instance()
        with patch("core.model_orchestrator._build_instance", return_value=mock_inst) as mock_build:
            r1 = orch.get(ModelRole.STT)
            r2 = orch.get(ModelRole.STT)
            # _build_instance should only be called once
            mock_build.assert_called_once()
            assert r1 is r2


class TestModelOrchestratorPreload:
    def setup_method(self):
        self.registry = ModelRegistry(EAGER_CONFIG)

    def test_preload_eager_loads_only_eager_specs(self):
        orch = ModelOrchestrator(self.registry)
        mock_inst = _make_mock_instance()
        with patch("core.model_orchestrator._build_instance", return_value=mock_inst) as mock_build:
            orch.preload_eager()
            # Only WAKE and VAD are marked eager=True
            assert mock_build.call_count == 2
            loaded_roles = {c.args[0].role for c in mock_build.call_args_list}
            assert loaded_roles == {ModelRole.WAKE, ModelRole.VAD}

    def test_after_preload_eager_no_reload_on_get(self):
        orch = ModelOrchestrator(self.registry)
        mock_inst = _make_mock_instance()
        with patch("core.model_orchestrator._build_instance", return_value=mock_inst) as mock_build:
            orch.preload_eager()
            preload_count = mock_build.call_count
            orch.get(ModelRole.WAKE)
            # No additional build call since it was preloaded
            assert mock_build.call_count == preload_count


class TestModelOrchestratorSwap:
    def setup_method(self):
        self.registry = ModelRegistry(EAGER_CONFIG)

    def test_swap_unloads_and_updates_registry(self):
        orch = ModelOrchestrator(self.registry)
        mock_inst = _make_mock_instance()
        with patch("core.model_orchestrator._build_instance", return_value=mock_inst):
            orch.get(ModelRole.STT)  # load first
        # Swap to a different model
        orch.swap(ModelRole.STT, "small")
        # Registry should reflect new name
        assert self.registry.get(ModelRole.STT).name == "small"
        # Instance should be unloaded
        assert ModelRole.STT not in orch._instances

    def test_swap_then_get_reloads(self):
        orch = ModelOrchestrator(self.registry)
        mock_v1 = _make_mock_instance()
        mock_v2 = _make_mock_instance()
        with patch("core.model_orchestrator._build_instance", return_value=mock_v1):
            orch.get(ModelRole.STT)
        orch.swap(ModelRole.STT, "small")
        with patch("core.model_orchestrator._build_instance", return_value=mock_v2):
            result = orch.get(ModelRole.STT)
        assert result is mock_v2

    def test_swap_calls_close_if_available(self):
        orch = ModelOrchestrator(self.registry)
        mock_inst = MagicMock(spec=["close"])
        with patch("core.model_orchestrator._build_instance", return_value=mock_inst):
            orch.get(ModelRole.STT)
        orch.swap(ModelRole.STT, "small")
        mock_inst.close.assert_called_once()

    def test_swap_calls_shutdown_if_no_close(self):
        orch = ModelOrchestrator(self.registry)
        mock_inst = MagicMock(spec=["shutdown"])
        with patch("core.model_orchestrator._build_instance", return_value=mock_inst):
            orch.get(ModelRole.STT)
        orch.swap(ModelRole.STT, "small")
        mock_inst.shutdown.assert_called_once()


class TestModelOrchestratorShutdown:
    def setup_method(self):
        self.registry = ModelRegistry(EAGER_CONFIG)

    def test_shutdown_unloads_all(self):
        orch = ModelOrchestrator(self.registry)
        mock_inst = _make_mock_instance()
        with patch("core.model_orchestrator._build_instance", return_value=mock_inst):
            orch.get(ModelRole.STT)
            orch.get(ModelRole.LLM)
        orch.shutdown()
        assert len(orch._instances) == 0

    def test_shutdown_idempotent(self):
        orch = ModelOrchestrator(self.registry)
        orch.shutdown()  # called with no loaded models — should not raise


class TestHailoSlotEnforcement:
    def setup_method(self):
        self.registry = ModelRegistry(HAILO_CONFIG)

    def test_two_hailo_models_raises(self):
        # Create a config where both stt and tts are on Hailo
        cfg = {
            "stt": {
                "name": "whisper-tiny",
                "backend": "hailo",
                "quant": "int8",
                "path": "/opt/hailo/whisper.hef",
                "version": "tiny",
                "eager": False,
            },
            "tts": {
                "name": "piper-hailo",
                "backend": "hailo",
                "quant": "none",
                "path": "/opt/hailo/piper.hef",
                "version": "medium",
                "eager": False,
            },
        }
        registry = ModelRegistry(cfg)
        orch = ModelOrchestrator(registry)
        mock_inst = _make_mock_instance()
        with patch("core.model_orchestrator._build_instance", return_value=mock_inst):
            orch.get(ModelRole.STT)  # succeeds, takes Hailo slot
            with pytest.raises(RuntimeError, match="Hailo"):
                orch.get(ModelRole.TTS)  # should fail

    def test_hailo_slot_released_after_swap(self):
        cfg = {
            "stt": {
                "name": "whisper-tiny",
                "backend": "hailo",
                "quant": "int8",
                "path": "/opt/hailo/whisper.hef",
                "version": "tiny",
                "eager": False,
            },
            "tts": {
                "name": "piper-hailo",
                "backend": "hailo",
                "quant": "none",
                "path": "/opt/hailo/piper.hef",
                "version": "medium",
                "eager": False,
            },
        }
        registry = ModelRegistry(cfg)
        orch = ModelOrchestrator(registry)
        mock_inst = _make_mock_instance()
        with patch("core.model_orchestrator._build_instance", return_value=mock_inst):
            orch.get(ModelRole.STT)
            orch.swap(ModelRole.STT, "whisper-small", "/opt/hailo/whisper-small.hef")
            assert not orch._hailo_slot_taken

    def test_cpu_model_loads_alongside_hailo(self):
        orch = ModelOrchestrator(self.registry)
        mock_inst = _make_mock_instance()
        with patch("core.model_orchestrator._build_instance", return_value=mock_inst):
            orch.get(ModelRole.STT)  # hailo
            orch.get(ModelRole.LLM)  # cpu — should not conflict
