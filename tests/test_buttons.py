"""Tests for hardware/buttons.py — all GPIO mocked via conftest.py."""
import sys
from unittest.mock import MagicMock


class FakeButton:
    """Minimal stand-in for gpiozero.Button that records handler assignments."""

    def __init__(self, pin, hold_time=None):
        self.pin = pin
        self.hold_time = hold_time
        self.when_pressed = None
        self.when_held = None


# Replace gpiozero.Button with FakeButton for all tests in this module
sys.modules["gpiozero"].Button = FakeButton

from hardware.buttons import DeviceButtons  # noqa: E402 — must come after stub


def _make_buttons(display=None, network=None, core=None):
    """Create a DeviceButtons instance with all dependencies mocked."""
    config = {"button_pins": {"power": 17, "action": 27, "interaction": 22}}
    display = display or MagicMock()
    network = network or MagicMock()
    core = core or MagicMock()
    return DeviceButtons(config, display, network, core), display, network, core


def test_machine_button_press_calls_display_wake():
    db, display, _, _ = _make_buttons()
    assert db.machine_btn.when_pressed is display.wake


def test_machine_button_hold_calls_graceful_shutdown():
    db, _, _, core = _make_buttons()
    assert db.machine_btn.when_held is core.graceful_shutdown


def test_machine_button_hold_time_is_5s():
    db, _, _, _ = _make_buttons()
    assert db.machine_btn.hold_time == 5


def test_action_button_press_calls_trigger_listening():
    db, _, _, core = _make_buttons()
    assert db.action_btn.when_pressed is core.trigger_listening


def test_action_button_hold_calls_cycle_mode():
    db, _, _, core = _make_buttons()
    assert db.action_btn.when_held is core.cycle_mode


def test_action_button_hold_time_is_1_5s():
    db, _, _, _ = _make_buttons()
    assert db.action_btn.hold_time == 1.5


def test_interaction_button_press_calls_cycle_agent():
    db, _, _, core = _make_buttons()
    assert db.interaction_btn.when_pressed is core.cycle_agent


def test_interaction_button_hold_calls_network_cycle_state():
    db, _, network, _ = _make_buttons()
    assert db.interaction_btn.when_held is network.cycle_state


def test_button_pins_from_config():
    db, _, _, _ = _make_buttons()
    assert db.machine_btn.pin == 17
    assert db.action_btn.pin == 27
    assert db.interaction_btn.pin == 22
