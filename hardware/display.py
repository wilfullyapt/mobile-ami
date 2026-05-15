"""
Display drivers for status OLED screens.

StatusDisplay   SH1106-based 128×64 OLED (default — Hosyond and most 1.3" modules).
SSD1306Display  Alternative for older SSD1306-based 0.96" / 1.3" modules.

Both expose the same DisplayDevice interface so the rest of the codebase
never needs to know which controller is fitted.
"""
import threading

import qrcode
from luma.core.interface.serial import i2c
from luma.oled.device import sh1106
from PIL import Image, ImageDraw, ImageFont

from hardware.abstract import DisplayDevice


_PAGE_DWELL_SEC = 5   # seconds each page is shown before cycling


class StatusDisplay(DisplayDevice):
    """
    SH1106 128×64 OLED display (I2C) with:
      - Configurable auto-off timeout (reset on every update)
      - wake() to turn screen on / reset timer (called by machine button)
      - Two-page cycling when a device server URL is set:
            page "stats" → battery / network / agent / server URL
            page "qr"    → full-screen QR code linking to the device server
    """

    def __init__(self, cfg: dict | None = None, timeout_sec: int | None = None, _luma_cls=None):
        """
        cfg          : hardware.display config dict (optional).
        timeout_sec  : seconds before the display sleeps; overrides cfg value.
        _luma_cls    : injected luma device class — used by SSD1306Display to
                       swap in ssd1306 without duplicating all the logic.
        """
        cfg = cfg or {}
        self._timeout_sec = (
            timeout_sec if timeout_sec is not None
            else cfg.get("timeout_sec", 15)
        )
        addr = int(cfg.get("i2c_address", "0x3C"), 16)

        luma_cls = _luma_cls or sh1106
        serial = i2c(port=1, address=addr)
        self.device = luma_cls(serial)

        self.font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10
        )
        self.big_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12
        )

        self._lock = threading.Lock()
        self._on = True
        self._timer: threading.Timer | None = None
        self._page = "stats"
        self._page_timer: threading.Timer | None = None
        self._server_url: str | None = None
        self._last: dict = {}

        self._reset_timeout()

    # ── DisplayDevice interface ───────────────────────────────────────────────

    def wake(self):
        """Called by machine button press — turn on for timeout_sec (or reset timer)."""
        with self._lock:
            if self._on:
                self._reset_timeout()
            else:
                self._turn_on()

    def toggle(self):
        """Flip screen on/off programmatically."""
        with self._lock:
            if self._on:
                self._turn_off()
            else:
                self._turn_on()

    def set_server_url(self, url: str | None):
        """Set (or clear) the device server URL; starts/stops QR page cycling."""
        with self._lock:
            self._server_url = url
            if self._on:
                if url:
                    self._start_page_cycling()
                else:
                    self._cancel_page_timer()
                    self._page = "stats"
                    self._render()

    def update(
        self,
        battery_pct: int,
        voltage: float,
        net_state: str,
        ssid: str,
        agent: str,
        interaction_mode: str = "",
        has_internet: bool = False,
        update_pending: bool = False,
        status_text: str = "Ready",
    ):
        """Refresh the stats cache and re-render if the display is on."""
        self._last = {
            "battery_pct": battery_pct,
            "voltage": voltage,
            "net_state": net_state,
            "ssid": ssid,
            "agent": agent,
            "interaction_mode": interaction_mode,
            "has_internet": has_internet,
            "update_pending": update_pending,
            "status_text": status_text,
        }
        with self._lock:
            if self._on:
                self._reset_timeout()
                if self._page == "stats":
                    self._render_stats()

    def update_mode(self, agent: str, interaction_mode: str | None = None):
        """Partial update: change the active agent (and optionally the mode)."""
        if self._last:
            self._last["agent"] = agent
            if interaction_mode is not None:
                self._last["interaction_mode"] = interaction_mode
            with self._lock:
                if self._on and self._page == "stats":
                    self._render_stats()

    # ── Internal: on/off ─────────────────────────────────────────────────────

    def _turn_on(self):
        self._on = True
        self._page = "stats"
        self.device.show()
        self._render()
        self._reset_timeout()
        if self._server_url:
            self._start_page_cycling()

    def _turn_off(self):
        self._on = False
        self._cancel_timer()
        self._cancel_page_timer()
        self.device.hide()

    def _auto_off(self):
        with self._lock:
            if self._on:
                self._turn_off()

    # ── Internal: timeout timer ───────────────────────────────────────────────

    def _reset_timeout(self):
        self._cancel_timer()
        self._timer = threading.Timer(self._timeout_sec, self._auto_off)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    # ── Internal: page cycling (stats ↔ qr) ──────────────────────────────────

    def _start_page_cycling(self):
        self._cancel_page_timer()
        self._page_timer = threading.Timer(_PAGE_DWELL_SEC, self._flip_page)
        self._page_timer.daemon = True
        self._page_timer.start()

    def _flip_page(self):
        with self._lock:
            if not self._on or not self._server_url:
                return
            self._page = "qr" if self._page == "stats" else "stats"
            self._render()
            self._start_page_cycling()

    def _cancel_page_timer(self):
        if self._page_timer is not None:
            self._page_timer.cancel()
            self._page_timer = None

    # ── Internal: rendering ───────────────────────────────────────────────────

    def _render(self):
        if self._page == "qr" and self._server_url:
            self._render_qr()
        else:
            self._render_stats()

    def _render_stats(self):
        d = self._last
        if not d:
            return
        image = Image.new("1", (self.device.width, self.device.height))
        draw = ImageDraw.Draw(image)

        bat = d.get("battery_pct", "--")
        volt = d.get("voltage", "--")
        net = d.get("net_state", "")
        ssid = d.get("ssid", "")
        agent = d.get("agent", "")
        imode = d.get("interaction_mode", "").upper()
        has_internet = d.get("has_internet", False)
        update_pending = d.get("update_pending", False)

        draw.text((0, 0), f"Bat: {bat}%  {volt}V", font=self.font, fill=255)

        net_indicator = "[+]" if has_internet else "[-]"
        draw.text((0, 12), f"Net: {net}{net_indicator} {ssid}", font=self.font, fill=255)

        draw.text((0, 24), agent.upper(), font=self.big_font, fill=255)

        status_part = "Update!" if update_pending else "Ready"
        mode_line = f"{imode}  {status_part}" if imode else status_part
        draw.text((0, 38), mode_line, font=self.font, fill=255)

        if self._server_url:
            short = self._server_url.replace("http://", "")
            draw.text((0, 52), short, font=self.font, fill=255)

        self.device.display(image)

    def _render_qr(self):
        if not self._server_url:
            return
        qr = qrcode.QRCode(version=1, box_size=3, border=0)
        qr.add_data(self._server_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color=1, back_color=0).convert("1")

        canvas = Image.new("1", (self.device.width, self.device.height), 0)
        qw, qh = qr_img.size
        x = (self.device.width - qw) // 2
        y = (self.device.height - qh) // 2
        canvas.paste(qr_img, (x, y))
        self.device.display(canvas)


class SSD1306Display(StatusDisplay):
    """Alternative driver for SSD1306-based 0.96″ or 1.3″ OLED modules."""

    def __init__(self, cfg: dict | None = None, timeout_sec: int | None = None):
        from luma.oled.device import ssd1306
        super().__init__(cfg, timeout_sec, _luma_cls=ssd1306)
