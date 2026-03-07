from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw, ImageFont
import qrcode

class StatusDisplay:
    def __init__(self):
        serial = i2c(port=1, address=0x3C)
        self.device = ssd1306(serial)
        self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        self.big_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)

    def update(self, battery_pct, voltage, net_state, ssid, mode, status_text="Ready"):
        image = Image.new("1", (self.device.width, self.device.height))
        draw = ImageDraw.Draw(image)
        draw.text((0, 0), f"Bat: {battery_pct}% {voltage}V", font=self.font, fill=255)
        draw.text((0, 12), f"Net: {net_state} {ssid}", font=self.font, fill=255)
        draw.text((0, 24), f"Mode: {mode.upper()}", font=self.big_font, fill=255)
        draw.text((0, 38), status_text, font=self.font, fill=255)
        self.device.display(image)

    def refresh(self):
        pass  # triggered by button

    def update_mode(self, mode):
        # called from cycle
        pass
