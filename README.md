# Pi Local AI Voice Assistant

Fully offline, battery-powered, self-contained voice assistant for Raspberry Pi 5 + Hailo-10H. Runs keyword spotting, VAD, STT, local LLM (or agent), and TTS entirely on-device. Includes screen, three physical buttons, RGB LEDs, auto-update on tagged releases, and graceful rollback.

**Features**
- 100% offline (no cloud ever)
- Hotword or manual trigger modes
- Switchable agents (QA or Block Timer)
- OLED status display + QR hotspot
- Automatic self-update (tagged releases only) with rollback
- Rechargeable 18650 UPS (3–5+ hours runtime)
- 3D-printable shell ready

## Quick Start (One-Time Install)
1. Flash **Raspberry Pi OS Lite (64-bit)** using the official Imager (enable SSH + WiFi).
2. Assemble the hardware (see [ASSEMBLY.md](ASSEMBLY.md)).
3. SSH in and run:
   ```bash
   git clone https://github.com/wilfullyapt/pi-local-ai-voice-assistant.git /opt/voice-assistant
   cd /opt/voice-assistant
   sudo bash install.sh
