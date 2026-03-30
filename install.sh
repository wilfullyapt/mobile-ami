#!/bin/bash
set -e

echo "=== Installing AMIni Voice Assistant ==="

# System update
apt update && apt full-upgrade -y

# Enable I2C & SPI (non-interactive)
raspi-config nonint do_i2c 0
raspi-config nonint do_spi 0

# Hailo AI HAT+ drivers (requires Hailo apt repo)
apt install -y apt-transport-https curl gnupg
curl -fsSL https://hailo-hailort.s3.eu-west-2.amazonaws.com/hailort-repo.gpg \
    | gpg --dearmor -o /usr/share/keyrings/hailo-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hailo-archive-keyring.gpg] \
https://hailo-hailort.s3.eu-west-2.amazonaws.com bookworm main" \
    > /etc/apt/sources.list.d/hailo.list
apt update
apt install -y hailo-all

# seeed-voicecard driver for KEYESTUDIO ReSpeaker 2-Mic Pi HAT V1 (WM8960)
git clone https://github.com/HinTak/seeed-voicecard.git /tmp/seeed-voicecard
cd /tmp/seeed-voicecard
./install.sh
cd -

# System dependencies
apt install -y python3-pip python3-venv i2c-tools libatlas-base-dev git \
    alsa-utils fonts-dejavu network-manager libportaudio2

# Project files live in the home directory — no /opt copy needed
DEPLOY_DIR="$HOME/mobile-ami"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$SCRIPT_DIR" != "$DEPLOY_DIR" ]; then
    mkdir -p "$DEPLOY_DIR"
    cp -r "$SCRIPT_DIR"/. "$DEPLOY_DIR/"
fi

# Python packages
pip3 install --break-system-packages -r "$DEPLOY_DIR/requirements.txt"

# Create ~/.amini/ directory tree for model and agent storage
AMI_DIR="$HOME/.amini"
mkdir -p \
    "$AMI_DIR/models/stt" \
    "$AMI_DIR/models/tts" \
    "$AMI_DIR/models/wake" \
    "$AMI_DIR/models/llm" \
    "$AMI_DIR/models/hailo" \
    "$AMI_DIR/agents"

# Install ollama
curl -fsSL https://ollama.com/install.sh | sh
systemctl enable ollama
systemctl start ollama

# Pull LLM into ~/.amini/models/llm/
export OLLAMA_MODELS="$AMI_DIR/models/llm"
ollama pull llama3.2:1b

# Install piper (aarch64 binary)
wget -q https://github.com/rhasspy/piper/releases/latest/download/piper_linux_aarch64.tar.gz -O /tmp/piper.tar.gz
tar -xzf /tmp/piper.tar.gz -C /usr/local/bin/
rm /tmp/piper.tar.gz

# Download piper voice model into ~/.amini/models/tts/
VOICES_DIR="$AMI_DIR/models/tts"
wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" \
    -O "$VOICES_DIR/en_US-lessac-medium.onnx"
wget -q "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" \
    -O "$VOICES_DIR/en_US-lessac-medium.onnx.json"

# Pre-download openwakeword models into ~/.amini/models/wake/
python3 -c "import openwakeword; openwakeword.utils.download_models(target_directory='$AMI_DIR/models/wake')"

# Pre-cache faster-whisper tiny model into ~/.amini/models/stt/
python3 -c "
from faster_whisper import WhisperModel
WhisperModel('tiny', device='cpu', compute_type='int8', download_root='$AMI_DIR/models/stt')
"

# Install systemd service
cp "$DEPLOY_DIR/amini.service" /etc/systemd/system/amini.service

# Substitute actual home dir into the service file (handles non-pi users)
sed -i "s|/home/pi|$HOME|g" /etc/systemd/system/amini.service

systemctl daemon-reload
systemctl enable amini.service

# Allow the running user to poweroff/reboot without a password (needed for power button hold)
echo "$USER ALL=(ALL) NOPASSWD: /bin/systemctl poweroff, /bin/systemctl reboot" \
    > /etc/sudoers.d/amini-poweroff
chmod 440 /etc/sudoers.d/amini-poweroff

echo "=== Installation complete! Rebooting in 5 seconds... ==="
sleep 5
reboot
