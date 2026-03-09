"""Tests for hardware/display.py — all luma.oled mocked via conftest.py."""
import sys
import time
from unittest.mock import MagicMock, patch


def _make_display(timeout_sec=60):
    """Create StatusDisplay with all hardware dependencies mocked."""
    fake_device = MagicMock()
    fake_device.width = 128
    fake_device.height = 64

    sys.modules["luma.core.interface.serial"].i2c = MagicMock(return_value=MagicMock())
    sys.modules["luma.oled.device"].ssd1306 = MagicMock(return_value=fake_device)

    # Ensure hardware.display is importable before patch() resolves it
    import hardware.display  # noqa: F401

    # Patch both ImageFont and ImageDraw so no real font file or drawing happens
    with patch("hardware.display.ImageFont") as mock_font, \
         patch("hardware.display.ImageDraw") as mock_draw, \
         patch("hardware.display.Image") as mock_image:
        mock_font.truetype.return_value = MagicMock()
        mock_draw.Draw.return_value = MagicMock()
        mock_image.new.return_value = MagicMock()
        from hardware.display import StatusDisplay
        disp = StatusDisplay(timeout_sec=timeout_sec)

    disp.device = fake_device
    # Replace draw/image constructors after init too (for update() calls in tests)
    disp._mock_image = mock_image
    disp._mock_draw = mock_draw
    return disp, fake_device


def _patch_draw(disp):
    """Context manager that suppresses PIL drawing in a display instance."""
    return patch.multiple(
        "hardware.display",
        Image=MagicMock(new=MagicMock(return_value=MagicMock())),
        ImageDraw=MagicMock(Draw=MagicMock(return_value=MagicMock())),
    )


def test_display_starts_on():
    disp, _ = _make_display()
    assert disp._on is True


def test_toggle_turns_screen_off_when_on():
    disp, device = _make_display()
    with _patch_draw(disp):
        disp.toggle()
    assert disp._on is False
    device.hide.assert_called_once()


def test_toggle_turns_screen_on_when_off():
    disp, device = _make_display()
    with _patch_draw(disp):
        disp.toggle()   # off
    device.reset_mock()
    with _patch_draw(disp):
        disp.toggle()   # on again
    assert disp._on is True
    device.show.assert_called_once()


def test_update_does_not_wake_sleeping_display():
    disp, device = _make_display()
    with _patch_draw(disp):
        disp.toggle()   # turn off
    device.reset_mock()
    with _patch_draw(disp):
        disp.update(50, 4.1, "wifi", "Home", "qa")
    device.display.assert_not_called()


def test_update_renders_when_on():
    disp, device = _make_display()
    with _patch_draw(disp):
        disp.update(80, 4.0, "wifi", "Home", "qa", "Ready")
    device.display.assert_called()


def test_update_stores_last_values():
    disp, _ = _make_display()
    with _patch_draw(disp):
        disp.update(75, 3.9, "hotspot", "AminiAI", "block_timer", "Listening")
    assert disp._last["battery_pct"] == 75
    assert disp._last["mode"] == "block_timer"


def test_update_mode_updates_cached_mode():
    disp, _ = _make_display()
    with _patch_draw(disp):
        disp.update(50, 4.1, "wifi", "Home", "qa")
        disp.update_mode("block_timer")
    assert disp._last["mode"] == "block_timer"


def test_set_server_url_stores_url():
    disp, _ = _make_display()
    with _patch_draw(disp):
        disp.set_server_url("http://192.168.1.5:5000")
    assert disp._server_url == "http://192.168.1.5:5000"


def test_set_server_url_none_clears_url():
    disp, _ = _make_display()
    with _patch_draw(disp):
        disp.set_server_url("http://192.168.1.5:5000")
        disp.set_server_url(None)
    assert disp._server_url is None


def test_set_server_url_cancels_page_timer_when_cleared():
    disp, _ = _make_display()
    with _patch_draw(disp):
        disp.update(50, 4.1, "wifi", "Home", "qa")
        disp.set_server_url("http://192.168.1.5:5000")
        disp.set_server_url(None)
    assert disp._page_timer is None or not disp._page_timer.is_alive()


def test_auto_off_fires_after_timeout():
    disp, device = _make_display(timeout_sec=0.1)
    assert disp._on is True
    time.sleep(0.3)
    assert disp._on is False
    device.hide.assert_called()


def test_render_qr_called_when_page_is_qr():
    disp, _ = _make_display()
    disp._server_url = "http://192.168.1.5:5000"
    disp._page = "qr"
    with patch.object(disp, "_render_qr") as mock_qr:
        disp._render()
    mock_qr.assert_called_once()


def test_render_stats_called_when_page_is_stats():
    disp, _ = _make_display()
    disp._server_url = "http://192.168.1.5:5000"
    disp._page = "stats"
    with patch.object(disp, "_render_stats") as mock_stats:
        disp._render()
    mock_stats.assert_called_once()


def test_page_cycles_when_server_url_set():
    disp, _ = _make_display()
    with _patch_draw(disp):
        disp.update(50, 4.1, "wifi", "Home", "qa")
        disp.set_server_url("http://192.168.1.5:5000")
    assert disp._page_timer is not None
