"""Unit tests for ModelOrchestrator.preload_for_mode()"""

import pytest
from unittest.mock import MagicMock, call, patch

from core.interaction_mode import InteractionMode
from core.model_registry import ModelRole
from core.model_orchestrator import ModelOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry(*available_roles: ModelRole):
    """Registry mock that has specs for the given roles only."""
    registry = MagicMock()

    def _get(role):
        if role in available_roles:
            spec = MagicMock()
            spec.role = role
            spec.backend = MagicMock()
            spec.backend.value = "cpu"
            return spec
        raise KeyError(role)

    registry.get.side_effect = _get
    registry.all_specs.return_value = []
    return registry


def _make_orchestrator(*available_roles: ModelRole):
    """Return an orchestrator with a patched _load and only specified roles available."""
    registry = _make_registry(*available_roles)
    orch = ModelOrchestrator(registry)
    orch._load = MagicMock()
    return orch


# ---------------------------------------------------------------------------
# MANUAL mode — no preloading
# ---------------------------------------------------------------------------

class TestPreloadForModeManual:
    def test_no_models_loaded_in_manual_mode(self):
        orch = _make_orchestrator(ModelRole.WAKE, ModelRole.VAD, ModelRole.STT)
        orch.preload_for_mode(InteractionMode.MANUAL)
        orch._load.assert_not_called()


# ---------------------------------------------------------------------------
# HOT_WORD mode — WAKE + VAD
# ---------------------------------------------------------------------------

class TestPreloadForModeHotWord:
    def test_loads_wake_and_vad(self):
        orch = _make_orchestrator(ModelRole.WAKE, ModelRole.VAD)
        orch.preload_for_mode(InteractionMode.HOT_WORD)
        loaded = {c.args[0] for c in orch._load.call_args_list}
        assert ModelRole.WAKE in loaded
        assert ModelRole.VAD in loaded

    def test_does_not_load_stt_in_hot_word_mode(self):
        orch = _make_orchestrator(ModelRole.WAKE, ModelRole.VAD, ModelRole.STT)
        orch.preload_for_mode(InteractionMode.HOT_WORD)
        loaded = {c.args[0] for c in orch._load.call_args_list}
        assert ModelRole.STT not in loaded

    def test_skips_role_not_in_registry(self):
        orch = _make_orchestrator(ModelRole.WAKE)  # no VAD
        orch.preload_for_mode(InteractionMode.HOT_WORD)
        loaded = {c.args[0] for c in orch._load.call_args_list}
        assert ModelRole.VAD not in loaded

    def test_skips_already_loaded_roles(self):
        orch = _make_orchestrator(ModelRole.WAKE, ModelRole.VAD)
        orch._instances[ModelRole.WAKE] = MagicMock()  # already loaded
        orch.preload_for_mode(InteractionMode.HOT_WORD)
        loaded = {c.args[0] for c in orch._load.call_args_list}
        assert ModelRole.WAKE not in loaded
        assert ModelRole.VAD in loaded


# ---------------------------------------------------------------------------
# ALLY mode — WAKE + VAD + STT + SPEAKER
# ---------------------------------------------------------------------------

class TestPreloadForModeAlly:
    def test_loads_wake_vad_stt_speaker(self):
        orch = _make_orchestrator(
            ModelRole.WAKE, ModelRole.VAD, ModelRole.STT, ModelRole.SPEAKER
        )
        orch.preload_for_mode(InteractionMode.ALLY)
        loaded = {c.args[0] for c in orch._load.call_args_list}
        assert ModelRole.WAKE in loaded
        assert ModelRole.VAD in loaded
        assert ModelRole.STT in loaded
        assert ModelRole.SPEAKER in loaded

    def test_skips_missing_speaker_role_gracefully(self):
        orch = _make_orchestrator(ModelRole.WAKE, ModelRole.VAD, ModelRole.STT)
        # No SPEAKER in registry — should not raise
        orch.preload_for_mode(InteractionMode.ALLY)
        loaded = {c.args[0] for c in orch._load.call_args_list}
        assert ModelRole.SPEAKER not in loaded

    def test_does_not_reload_already_loaded(self):
        orch = _make_orchestrator(
            ModelRole.WAKE, ModelRole.VAD, ModelRole.STT, ModelRole.SPEAKER
        )
        # Pre-populate all instances
        for role in (ModelRole.WAKE, ModelRole.VAD, ModelRole.STT, ModelRole.SPEAKER):
            orch._instances[role] = MagicMock()
        orch.preload_for_mode(InteractionMode.ALLY)
        orch._load.assert_not_called()

    def test_load_exception_does_not_propagate(self):
        orch = _make_orchestrator(ModelRole.STT, ModelRole.SPEAKER)
        orch._load.side_effect = RuntimeError("model load failed")
        # Should not raise
        orch.preload_for_mode(InteractionMode.ALLY)
