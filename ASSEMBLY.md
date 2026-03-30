# Hardware Assembly Guide – Full BOM & First Boot

## Bill of Materials (verified March 2026)

### Core Components
1. **Raspberry Pi 5 8GB** (~$125)
   - Official: https://www.raspberrypi.com/products/raspberry-pi-5/
   - CanaKit: https://www.canakit.com/raspberry-pi-5-8gb.html
   - Amazon: https://www.amazon.com/Raspberry-Pi-8GB-SC1112-Quad-core/dp/B0CK2FCG1K

2. **Raspberry Pi AI HAT+ 2 (Hailo-10H)** (~$130)
   - Official: https://www.raspberrypi.com/products/ai-hat-plus-2/
   - PiShop.us: https://www.pishop.us/product/raspberry-pi-ai-hat-2/
   - Seeed Studio: https://www.seeedstudio.com/Raspberry-Pi-Al-HAT-2-p-6648.html

3. **Geekworm X1202 4-Cell 18650 UPS HAT** (~$47)
   - Official: https://geekworm.com/products/x1202
   - Amazon: https://www.amazon.com/Geekworm-X1202-Raspberry-Shutdown-Detection/dp/B0CRZ4ZXQW

4. **KEYESTUDIO ReSpeaker 2-Mic Pi HAT V1** (~$15–25)
   - WM8960 audio codec (I2S + I2C). 3× APA102 LEDs on SPI0 (MOSI=GPIO 10, CLK=GPIO 11).
   - Requires `seeed-voicecard` ALSA driver — **do not substitute with a generic WM8960 HAT**.
   - KEYESTUDIO store or Amazon (search "KEYESTUDIO ReSpeaker 2-Mic Pi HAT").

5. **Raspberry Pi 5 Active Cooler** (~$12)
   - Official: https://www.raspberrypi.com/products/active-cooler/
   - Adafruit: https://www.adafruit.com/product/5815

6. **18650 Batteries – Molicel P28A (flat-top, unprotected)** (4× ~$10–20 total)
   - https://www.18650batterystore.com/products/molicel-p28a

### Screen & Buttons
7. **1.3" SH1106 OLED (I2C, 128×64)** (~$6–10)
   - Controller is **SH1106** — do NOT buy an SSD1306 module (different controller, won't display correctly).
   - Amazon search: "1.3 inch SH1106 OLED I2C 128x64"

8. **Tactile Push Buttons 6×6mm** (3×, any kit) (~$3)
   - Amazon: https://www.amazon.com/6x6mm-Tactile-Switch-Module-Electronics/dp/B0FX87FTK9
   - Adafruit example: https://www.adafruit.com/product/367

**Optional**: 20 W+ USB-C charger, 64 GB microSD, M2.5 standoff kit, jumper wires.

**Total**: ~$350–480.

## Pin Map

| GPIO | Pin | Function | Used by |
|---|---|---|---|
| 2 (SDA) | 3 | I2C data | OLED (0x3C), WM8960 (0x1A), X1202 gauge (0x36) |
| 3 (SCL) | 5 | I2C clock | (shared bus) |
| 10 (MOSI) | 19 | SPI0 data | ReSpeaker APA102 LEDs |
| 11 (CLK) | 23 | SPI0 clock | ReSpeaker APA102 LEDs |
| 17 | 11 | Button input | Power/machine button → GND |
| 18 (PCM_CLK) | 12 | I2S bit clock | ReSpeaker audio — **reserved, do not use** |
| 19 (PCM_FS) | 35 | I2S LR clock | ReSpeaker audio — **reserved, do not use** |
| 20 (PCM_DIN) | 38 | I2S data in | ReSpeaker audio — **reserved, do not use** |
| 21 (PCM_DOUT) | 40 | I2S data out | ReSpeaker audio — **reserved, do not use** |
| 22 | 15 | Button input | Interaction button → GND |
| 27 | 13 | Button input | Action button → GND |

The AI HAT+ 2 (Hailo-10H) connects via PCIe FFC — it does **not** use the 40-pin GPIO header and has no pin conflicts.

## Wiring (discrete components only — HAT handles its own pins)
- OLED: VCC → 3.3 V (pin 1), GND → GND, SDA → GPIO 2 (pin 3), SCL → GPIO 3 (pin 5)
- Power button: one leg → GND, other → GPIO 17 (pin 11)
- Action button: one leg → GND, other → GPIO 27 (pin 13)
- Interaction button: one leg → GND, other → GPIO 22 (pin 15)
- ReSpeaker LEDs and audio are handled by the HAT itself.

## Assembly Steps
1. Stack: X1202 (bottom) → ReSpeaker HAT → Pi 5 on top. AI HAT+ 2 attaches via PCIe FFC ribbon. Secure with standoffs.
2. Attach Active Cooler to Pi 5.
3. Solder/wire OLED and three buttons (use dupont connectors or direct to header).
4. Insert 4× Molicel P28A batteries into X1202 (correct polarity).
5. Flash Raspberry Pi OS Lite (64-bit) with SSH + WiFi enabled.
6. Insert SD, power via X1202 USB-C charger.
7. SSH in and run the `install.sh` from README.md.
8. `install.sh` installs the `seeed-voicecard` ALSA driver automatically — ReSpeaker audio is enabled after the reboot.

## First Boot
- Device boots → OLED shows battery/network.
- Service starts automatically.
- Say "Hey Assistant" or press buttons. Done!

## Notes
- `sudo systemctl poweroff` is called on 5-second power button hold — ensure the Pi user has passwordless sudo for `systemctl poweroff` (the `install.sh` sets this up).
- All I2C devices share the same bus (GPIO 2/3). Addresses are distinct: 0x3C (OLED), 0x1A (WM8960), 0x36 (X1202 fuel gauge) — no conflicts.
- Heat managed by Active Cooler. Ready for your 3D-printed shell.
