# Developer Guide

## Quick Start (Linux / macOS / WSL2)

```bash
git clone https://github.com/wilfullyapt/mobile-ami.git
cd mobile-ami

# Install uv once (fast Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install dev dependencies
make dev

# Run the full test suite (no hardware required — all deps are mocked)
make test
```

`make test` runs all 115+ tests in under 30 seconds without any Raspberry Pi hardware,
Ollama, Whisper, or other ML deps installed.

## Available Make Targets

| Target | Description |
|---|---|
| `make dev` | Create `.venv` and install project + dev deps |
| `make test` | Run full test suite |
| `make test-cov` | Run tests with coverage report |
| `make lint` | Run ruff linter |
| `make clean` | Remove `.venv`, caches, build artifacts |

## Project Dependencies

Dependencies are declared in `pyproject.toml`:

- **`dependencies`** — portable deps that work on any platform (used in CI and dev)
- **`[dev]`** — test tools: `pytest`, `pytest-cov`
- **`[pi]`** — full Pi runtime deps: `gpiozero`, `openwakeword`, `faster-whisper`, etc.

To install all Pi deps locally (if your system supports them):
```bash
uv pip install -e ".[dev,pi]"
```

## Running Specific Tests

```bash
uv run pytest tests/test_agents.py -v
uv run pytest tests/ -k "test_ami_paths" -v
```

## Pi Deployment

See `install.sh` for full Pi setup (Hailo drivers, audio HAT, system services).
The `[pi]` extras in `pyproject.toml` match `requirements.txt` for pip compatibility.

## Versioning

Versions are derived from git tags via `hatch-vcs`:
- `git tag v0.1.0` → package version `0.1.0`
- Untagged commits → `0.0.dev<n>+g<hash>`

To tag a release:
```bash
git tag v0.1.0
git push origin v0.1.0
```
