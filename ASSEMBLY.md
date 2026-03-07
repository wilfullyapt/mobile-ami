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

4. **Geekworm Raspi Voice HAT (WM8960)** (~$30–50)  
   - Wiki & purchase guidance: https://wiki.geekworm.com/Raspi_Voice_HAT  
   - Buy via Geekworm store[](https://geekworm.com/collections/raspberry-pi-5) or eBay resellers (search "Geekworm Raspi Voice HAT").

5. **Raspberry Pi 5 Active Cooler** (~$12)  
   - Official: https://www.raspberrypi.com/products/active-cooler/  
   - Adafruit: https://www.adafruit.com/product/5815

6. **18650 Batteries – Molicel P28A (flat-top, unprotected)** (4× ~$10–20 total)  
   - https://www.18650batterystore.com/products/molicel-p28a

### Screen & Buttons
7. **1.3" SSD1306 OLED (I2C, 128×64)** (~$6–10)  
   - Amazon (Hosyond 5-pack): https://www.amazon.com/Hosyond-Display-Compatible-Arduino-Raspberry/dp/B0C3L7N917

8. **Tactile Push Buttons 6×6mm** (2–3×, any kit) (~$3)  
   - Amazon: https://www.amazon.com/6x6mm-Tactile-Switch-Module-Electronics/dp/B0FX87FTK9  
   - Adafruit example: https://www.adafruit.com/product/367

**Optional**: 20 W+ USB-C charger, 64 GB microSD, M2.5 standoff kit, jumper wires.

**Total**: ~$350–480.

## Wiring (all to 40-pin header)
- OLED: VCC → 3.3 V, GND → GND, SDA → GPIO 2 (pin 3), SCL → GPIO 3 (pin 5)
- Power button: one leg → GND, other → GPIO 17 (pin 11)
- Action button: one leg → GND, other → GPIO 27 (pin 13)
- Interaction button: one leg → GND, other → GPIO 22 (pin 15)
- Voice HAT LEDs & audio already handled by HAT.

## Assembly Steps
1. Stack: X1202 (bottom) → Voice HAT → AI HAT+ 2 on PCIe. Secure with standoffs.
2. Attach Active Cooler.
3. Solder/wire OLED and three buttons (use dupont or direct to header).
4. Insert 4× Molicel P28A batteries (correct polarity).
5. Flash Raspberry Pi OS Lite (64-bit) with SSH + WiFi enabled.
6. Insert SD, power via X1202 USB-C charger.
7. SSH in and run the `install.sh` from README.md.

## First Boot
- Device boots → OLED shows battery/network.
- Service starts automatically.
- Say "Hey Assistant" or press buttons. Done!

All GPIO/I2C conflicts resolved. Heat managed. Ready for your 3D-printed shell.
