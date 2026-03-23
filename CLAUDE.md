# mobile-ami — Claude Memory

## Project Goal

**mobile-ami** is a handheld, fully offline voice AI assistant running on a Raspberry Pi with a Hailo-10H AI accelerator HAT. The device runs 5 AI models locally (STT, TTS, LLM, wake word, VAD) and supports multiple specialized agents — built-in and 3rd-party plugins installed from GitHub — that the user can cycle through via a physical button.

---

## Architecture (current branch: `claude/review-claude-md-f9B8r`)

### Layer overview (bottom-up)

```
~/.amini/  (user data: models + agent plugins — separate from project source)
    ↓
Hardware (audio, LEDs, buttons, display, power, network)
    ↓
Model Layer (AmiPaths → registry → orchestrator → model wrappers)
    ↓
Tool Layer (BaseTool, ToolRegistry, TimerTool)
    ↓
Agent Layer (BaseAgent → QAAgent / BlockTimerAgent / plugin agents)
    ↓
Pipeline (VoicePipeline: listen → transcribe → respond → speak)
    ↓
cli.py / main.py (VoiceAssistant entry point)
```

### Key files and their roles

| File | Purpose |
|---|---|
| `cli.py` | `amini` CLI — `run`, `install`, `list`, `remove`, `update`, `models`, `test` |
| `main.py` | `VoiceAssistant` class — wires all layers, runs wake loop on main thread |
| `config.yaml` | All model config (name, backend, quant, path, version, eager) |
| `core/ami_paths.py` | `AmiPaths` — file-ops object for `~/.amini/`; path resolution for models and agents |
| `core/addon_installer.py` | `AddonInstaller` — GitHub clone → validate → pre-install test → install → post-install test |
| `core/config_manager.py` | `ConfigManager` — safe read/write of `config.yaml` with `EDITABLE_PATHS` whitelist. `ensure_config()` for first-run copy from `config.yaml.default`. |
| `core/model_registry.py` | `ModelSpec` dataclass + `ModelRegistry(config, paths=None)`. Enums: `ModelRole`, `Backend`, `QuantType` |
| `core/model_orchestrator.py` | `ModelOrchestrator` — lazy loading, Hailo slot enforcement, hot-swap via `swap()`, `preload_eager()` |
| `core/pipeline.py` | `VoicePipeline` with 4 stages + `PipelineContext` dataclass |
| `core/sst.py` | faster-whisper STT wrapper — `download_root=spec.path` → `~/.amini/models/stt/` |
| `core/tts.py` | Piper TTS wrapper — model path from spec (no hardcoded fallback) |
| `core/llm.py` | Ollama LLM wrapper — sets `OLLAMA_MODELS=spec.path` → `~/.amini/models/llm/` |
| `core/vad.py` | WebRTC VAD wrapper |
| `core/wake_detector.py` | OpenWakeWord wrapper — `target_directory=spec.path` → `~/.amini/models/wake/` |
| `core/agent_manager.py` | `AgentManager(slugs, orchestrator, tool_registry, paths=None)` — loads built-ins + `~/.amini/agents/` plugins |
| `agents/base_agent.py` | Abstract `BaseAgent(orchestrator, tool_registry)` — `process()` + `get_tools()` |
| `agents/qa_agent.py` | General Q&A with agentic tool loop (max 5 rounds) |
| `agents/block_timer_agent.py` | Focus timer — LLM parses natural language, calls `set_timer` tool |
| `agents/tools/base_tool.py` | `BaseTool` ABC + `ToolParam` dataclass + `to_llm_schema()` (Ollama format) |
| `agents/tools/tool_registry.py` | `ToolRegistry` — register, get, execute, all_schemas |
| `agents/tools/timer_tool.py` | `TimerTool` — starts background thread timer, speaks start/complete via injected callback |
| `agents/tools/tool_registry.py` | `ToolRegistry` — register, get, execute, all_schemas. `FilteredToolRegistry` — per-agent proxy filtered by equipped sub-agent slugs |
| `agents/subagents/dependency_subagent.py` | `DependencySubAgent` — checks/reconciles addon requirements; works without orchestrator |
| `core/server/routes/config.py` | `/api/config/agents` — list + live toggle + sub-agent equip; `/api/config/device` — device settings |
| `tests/` | 165+ pytest unit tests covering all components |

---

## User Data Directory: `~/.amini/`

All runtime data lives here — separate from the project source tree at `~/mobile-ami/`.

```
~/.amini/
├── models/
│   ├── stt/      faster-whisper download_root
│   ├── tts/      Piper .onnx + .json voice files
│   ├── wake/     OpenWakeWord downloaded models
│   ├── llm/      Ollama blobs (OLLAMA_MODELS env points here)
│   └── hailo/    future .hef files for Hailo-10H
└── agents/
    └── <name>/   3rd-party plugin agents (manifest.json + agent.py)
```

---

## 3rd-Party Agent Plugin Contract

Agents installed from GitHub into `~/.amini/agents/<name>/` must contain:

| File | Required | Purpose |
|---|---|---|
| `manifest.json` | yes | `name`, `version`, `entry_class` fields |
| `agent.py` | yes | class extending `BaseAgent` with `process()` and `get_tools()` |
| `requirements.txt` | no | pip deps installed on install |
| `tests/test_unit*.py` | recommended | run pre-install (mocked) |
| `tests/test_integration*.py` | recommended | run post-install (may use real orchestrator) |

Install flow: `amini install user/repo` → clone → validate → pre-install unit tests → copy → pip install → post-install import + integration tests.

---

## CLI Usage

```
amini run                        # start voice assistant
amini install user/repo          # install 3rd-party agent from GitHub
amini list                       # list built-in + installed agents
amini remove <name>              # uninstall agent
amini update <name> user/repo    # update installed agent
amini models pull                # download/cache all configured models
amini models list                # show model paths and backends
amini test                       # run full project test suite
amini test <agent>               # run specific agent's tests
```

---

## Design decisions to remember

- **`config.yaml` is user-local; `config.yaml.default` is the committed template** — `ConfigManager.ensure_config()` copies default → config on first run. `config.yaml` is gitignored.
- **`ConfigManager.EDITABLE_PATHS` whitelist** — only approved config keys can be written via the server. Hardware pins, model backends, etc. are read-only from the web UI.
- **`FilteredToolRegistry` is a live proxy** — filters the global registry by equipped sub-agent slugs at call time. Equip changes take effect immediately without restarting agents.
- **Agent enable/disable is live** — `AgentManager.enable_agent()` / `disable_agent()` add/remove agents from the cycling list in-place. Sub-agent equip is also live via `update_equipped_sub_agents()`.
- **`DependencySubAgent` works without an orchestrator** — pass `orchestrator=None`; it only uses `packaging` + `subprocess`. Used by `AddonInstaller.preview()` and `install()`.
- **Add-on packages support multi-agent layout** — `manifest.json` with `agents: [...]` and `sub_agents: [...]` keys. Legacy single-file `agent.py` repos still work unchanged.
- **Preview gate for addon install** — web UI requires Preview to be loaded before Install activates. Shows README, agent/sub-agent list, and dependency conflicts.
- **`requirements.in` is human-maintained; `requirements.txt` is compiled output** — run `pip-compile requirements.in` after adding deps (`pip-tools` in dev dependencies).
- **`AmiPaths` is the single source of truth for `~/.amini/`** — pass it to `ModelRegistry` and `AgentManager`; never hardcode `~/.amini/` paths elsewhere.
- **`ModelRegistry(config, paths=None)`** — when `paths` is provided, `spec.path` is auto-resolved: `null` → role model dir, bare filename → role model dir / filename, absolute → unchanged. Backward compatible: `paths=None` preserves original behaviour.
- **`AgentManager` loads built-ins then plugins** — built-ins (`qa`, `block_timer`) always available; `~/.amini/agents/<slug>/` plugins loaded dynamically via importlib.
- **`ModelRole` is the primary key** — `orchestrator.get(ModelRole.STT)` everywhere, never string lookups after registry parse.
- **`eager: true` in config** — VAD and WAKE load at startup; others load lazily on first use.
- **Hailo-10H is a single exclusive resource** — `ModelOrchestrator._hailo_slot_taken` flag prevents two Hailo models from loading simultaneously. `swap()` releases the slot.
- **`sst.py` not `stt.py`** — the STT wrapper file has a typo in its name; keep it as-is to avoid breaking imports.
- **Tool-calling uses Ollama's native format** — `to_llm_schema()` produces OpenAI-compatible dicts; `chat_with_tools()` returns `(text, parsed_calls)`.
- **`BlockTimerAgent` gets TTS from orchestrator in `get_tools()`** — so `TimerTool.on_speak` always has a live TTS instance even after a hot-swap.
- **Tests mock all hardware/library deps** — tests run without any Raspberry Pi hardware, Ollama, Whisper, etc. installed.
- **`amini.service` sets `OLLAMA_MODELS`** — the systemd unit injects `OLLAMA_MODELS=/home/pi/.amini/models/llm` so Ollama uses the user home dir.

---

## Hailo integration status

Hailo-10H is **wired but not yet active**. The `Backend.HAILO` enum and `_hailo_slot_taken` enforcement exist. To activate:
- Set `backend: hailo` and `path: hailo/whisper_tiny.hef` (filename → `~/.amini/models/hailo/`) in `config.yaml`
- Add a `HailoSTT` (or similar) wrapper class in `core/hailo_stt.py`
- Add a branch in `model_orchestrator._build_instance()` for `spec.backend == Backend.HAILO`

---

## Running tests

```bash
python -m pytest tests/ -q
```

No hardware required — all external deps are mocked.

### Testing a specific installed agent

```bash
amini test <agent-name>
# or directly:
python -m pytest ~/.amini/agents/<name>/tests/ -q
```
