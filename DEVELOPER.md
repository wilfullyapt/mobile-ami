# Developer Guide

## Recommended Setup (Linux – Ubuntu/Debian/Pi OS)
```bash
git clone https://github.com/wilfullyapt/pi-local-ai-voice-assistant.git
cd pi-local-ai-voice-assistant
```

### Install UV once<a href="https://docs.astral.sh/uv/getting-started/installation/" target="_blank" rel="noopener noreferrer nofollow"></a>
curl -LsSf https://astral.sh/uv/install.sh | sh

```bash
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```
