import apa102

class LEDs:
    def __init__(self):
        self.strip = apa102.APA102(12, 18, 23)  # APA102 on Voice HAT SPI

    def set_color(self, color):
        if color == "green": self.strip.set_pixel(0, 0, 255, 0)
        elif color == "blue": self.strip.set_pixel(0, 0, 0, 255)
        elif color == "red": self.strip.set_pixel(0, 255, 0)
        self.strip.show()
