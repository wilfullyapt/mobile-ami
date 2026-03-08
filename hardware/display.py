import threading

import qrcode
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw, ImageFont


_PAGE_DWELL_SEC = 5   # seconds each page is shown before cycling


class StatusDisplay:
    """
    SSD1306 128×64 OLED display with:
      - 15-second auto-off timeout (reset on every update)
      - toggle() to turn screen on or off (called by machine button)
      - Two-page cycling when a device server URL is set:
          page "stats" → battery / network / agent / server URL
          page "qr"    → full-screen QR code linking to device server
    """

    def __init__(self, timeout_sec: int = 15):
        serial = i2c(port=1, address=0x3C)
        self.device = ssd1306(serial)
        self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        self.big_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12
        )

        self._lock = threading.Lock()
        self._on = True
        self._timeout_sec = timeout_sec
        self._timer: threading.Timer | None = None
        self._page = "stats"
        self._page_timer: threading.Timer | None = None
        self._server_url: str | None = None

        # Cache of last stats for re-render
        self._last: dict = {}

        self._reset_timeout()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def toggle(self):
        """Called by machine button press — flip screen on/off."""
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
        mode: str,
        status_text: str = "Ready",
    ):
        """
        Refresh the stats page cache and re-render if the screen is on.
        Does NOT wake a sleeping display.
        """
        self._last = {
            "battery_pct": battery_pct,
            "voltage": voltage,
            "net_state": net_state,
            "ssid": ssid,
            "mode": mode,
            "status_text": status_text,
        }
        with self._lock:
            if self._on:
                self._reset_timeout()
                if self._page == "stats":
                    self._render_stats()

    def update_mode(self, mode: str):
        """Partial update: change the agent mode field only."""
        if self._last:
            self._last["mode"] = mode
            with self._lock:
                if self._on and self._page == "stats":
                    self._render_stats()

    # ------------------------------------------------------------------
    # Internal: on/off
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Internal: timeout timer
    # ------------------------------------------------------------------

    def _reset_timeout(self):
        self._cancel_timer()
        self._timer = threading.Timer(self._timeout_sec, self._auto_off)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    # ------------------------------------------------------------------
    # Internal: page cycling (stats ↔ qr)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Internal: rendering
    # ------------------------------------------------------------------

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
        mode = d.get("mode", "")
        status = d.get("status_text", "Ready")

        draw.text((0, 0), f"Bat: {bat}% {volt}V", font=self.font, fill=255)
        draw.text((0, 12), f"Net: {net} {ssid}", font=self.font, fill=255)
        draw.text((0, 24), f"Mode: {mode.upper()}", font=self.big_font, fill=255)
        draw.text((0, 38), status, font=self.font, fill=255)

        if self._server_url:
            # Show abbreviated server URL on the last line
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

        # Centre the QR image on the 128×64 canvas
        canvas = Image.new("1", (self.device.width, self.device.height), 0)
        qw, qh = qr_img.size
        x = (self.device.width - qw) // 2
        y = (self.device.height - qh) // 2
        canvas.paste(qr_img, (x, y))
        self.device.display(canvas)
