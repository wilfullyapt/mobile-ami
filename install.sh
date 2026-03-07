#!/bin/bash
set -e

echo "=== Installing Pi Local AI Voice Assistant ==="

# System update
apt update && apt full-upgrade -y

# Enable I2C & SPI (non-interactive)
raspi-config nonint do_i2c 0
raspi-config nonint do_spi 0

# Hailo AI HAT+ 2 drivers (official for Trixie)
apt install -y dkms hailo-all

# WM8960 Voice HAT audio driver (Geekworm uses same chipset as Waveshare)
git clone https://github.com/waveshare/WM8960-Audio-HAT.git /tmp/wm8960
cd /tmp/wm8960
sudo ./install.sh
cd -

# System dependencies
apt install -y python3-pip python3-venv i2c-tools libatlas-base-dev git

# Python packages (system-wide for simplicity with systemd)
pip3 install --break-system-packages -r requirements.txt

# Install systemd service
cp voice-assistant.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable voice-assistant.service

echo "=== Installation complete! Rebooting in 5 seconds... ==="
sleep 5
reboot
