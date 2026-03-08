"""Unit tests for core/interaction_mode.py"""

import pytest
from core.interaction_mode import InteractionMode, ModeManager
from core.ami_paths import AmiPaths


@pytest.fixture
def paths(tmp_path):
    return AmiPaths(root=str(tmp_path / "amini"))


class TestInteractionMode:
    def test_values_are_strings(self):
        assert InteractionMode.MANUAL == "manual"
        assert InteractionMode.HOT_WORD == "hot_word"
        assert InteractionMode.ALLY == "ally"


class TestModeManager:
    def test_defaults_to_hot_word_when_no_settings(self, paths):
        mgr = ModeManager(paths)
        assert mgr.mode == InteractionMode.HOT_WORD

    def test_respects_custom_default(self, paths):
        mgr = ModeManager(paths, default=InteractionMode.MANUAL)
        assert mgr.mode == InteractionMode.MANUAL

    def test_loads_from_persisted_settings(self, paths):
        paths._root.mkdir(parents=True, exist_ok=True)
        paths.save_settings({"interaction_mode": "ally"})
        mgr = ModeManager(paths)
        assert mgr.mode == InteractionMode.ALLY

    def test_migrates_hotword_trigger_true(self, paths):
        paths._root.mkdir(parents=True, exist_ok=True)
        paths.save_settings({"hotword_trigger": True})
        mgr = ModeManager(paths)
        assert mgr.mode == InteractionMode.HOT_WORD

    def test_migrates_hotword_trigger_false(self, paths):
        paths._root.mkdir(parents=True, exist_ok=True)
        paths.save_settings({"hotword_trigger": False})
        mgr = ModeManager(paths)
        assert mgr.mode == InteractionMode.MANUAL

    def test_cycle_advances_through_order(self, paths):
        mgr = ModeManager(paths, default=InteractionMode.MANUAL)
        assert mgr.cycle() == InteractionMode.HOT_WORD
        assert mgr.cycle() == InteractionMode.ALLY
        assert mgr.cycle() == InteractionMode.MANUAL  # wraps

    def test_cycle_persists(self, paths):
        mgr = ModeManager(paths, default=InteractionMode.MANUAL)
        mgr.cycle()  # → hot_word
        mgr2 = ModeManager(paths)
        assert mgr2.mode == InteractionMode.HOT_WORD

    def test_set_changes_mode(self, paths):
        mgr = ModeManager(paths)
        mgr.set(InteractionMode.ALLY)
        assert mgr.mode == InteractionMode.ALLY

    def test_is_manual(self, paths):
        mgr = ModeManager(paths, default=InteractionMode.MANUAL)
        assert mgr.is_manual()
        assert not mgr.is_hot_word()
        assert not mgr.is_ally()

    def test_is_ally(self, paths):
        mgr = ModeManager(paths, default=InteractionMode.ALLY)
        assert mgr.is_ally()

    def test_label_is_non_empty(self, paths):
        mgr = ModeManager(paths)
        assert len(mgr.label) > 5

    def test_persists_hotword_trigger_in_sync(self, paths):
        """Backward-compat: hotword_trigger should remain in settings."""
        mgr = ModeManager(paths, default=InteractionMode.MANUAL)
        mgr.set(InteractionMode.HOT_WORD)
        s = paths.load_settings()
        assert s["hotword_trigger"] is True

    def test_invalid_stored_value_falls_back_to_default(self, paths):
        paths._root.mkdir(parents=True, exist_ok=True)
        paths.save_settings({"interaction_mode": "bogus"})
        mgr = ModeManager(paths, default=InteractionMode.MANUAL)
        assert mgr.mode == InteractionMode.MANUAL
