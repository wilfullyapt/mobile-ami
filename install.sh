#!/bin/bash
set -e

echo "=== Installing AMIni Voice Assistant ==="

# System update
apt update && apt full-upgrade -y

# Enable I2C & SPI (non-interactive)
raspi-config nonint do_i2c 0
raspi-config nonint do_spi 0

# Hailo AI HAT+ drivers
apt install -y dkms hailo-all

# WM8960 Voice HAT audio driver
git clone https://github.com/waveshare/WM8960-Audio-HAT.git /tmp/wm8960
cd /tmp/wm8960
sudo ./install.sh
cd -

# System dependencies
apt install -y python3-pip python3-venv i2c-tools libatlas-base-dev git \
    alsa-utils fonts-dejavu network-manager

# Copy project files to deployment path
DEPLOY_DIR="/opt/voice-assistant"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$SCRIPT_DIR" != "$DEPLOY_DIR" ]; then
    mkdir -p "$DEPLOY_DIR"
    cp -r "$SCRIPT_DIR"/. "$DEPLOY_DIR/"
fi

# Python packages
pip3 install --break-system-packages -r "$DEPLOY_DIR/requirements.txt"

# Install ollama
curl -fsSL https://ollama.com/install.sh | sh
systemctl enable ollama
systemctl start ollama
ollama pull llama3.2:1b

# Install piper (aarch64 binary)
wget -q https://github.com/rhasspy/piper/releases/latest/download/piper_linux_aarch64.tar.gz -O /tmp/piper.tar.gz
tar -xzf /tmp/piper.tar.gz -C /usr/local/bin/
rm /tmp/piper.tar.gz

# Download piper voice model
VOICES_DIR="$DEPLOY_DIR/piper-voices"
mkdir -p "$VOICES_DIR"
wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" \
    -O "$VOICES_DIR/en_US-lessac-medium.onnx"
wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" \
    -O "$VOICES_DIR/en_US-lessac-medium.onnx.json"

# Pre-download openwakeword models (requires internet)
python3 -c "import openwakeword; openwakeword.utils.download_models()"

# Pre-cache faster-whisper tiny model
python3 -c "from faster_whisper import WhisperModel; WhisperModel('tiny', device='cpu', compute_type='int8')"

# Install systemd service
cp "$DEPLOY_DIR/amini.service" /etc/systemd/system/amini.service
systemctl daemon-reload
systemctl enable amini.service

echo "=== Installation complete! Rebooting in 5 seconds... ==="
sleep 5
reboot
