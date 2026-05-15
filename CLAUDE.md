# mobile-ami — Claude Memory

## Project Goal

**mobile-ami** is a handheld, fully offline voice AI assistant running on a Raspberry Pi with a Hailo-10H AI accelerator HAT. The device runs 5 AI models locally (STT, TTS, LLM, wake word, VAD) and supports multiple specialized agents — built-in and 3rd-party add-ons installed from GitHub — that the user can cycle through via a physical button or configure from the web UI.

---

## Hardware Bill of Materials (confirmed March 2026)

| Component | Notes |
|---|---|
| **Raspberry Pi 5 8GB** | Main compute board |
| **Raspberry Pi AI HAT+ 2 (Hailo-10H)** | Connects via PCIe FFC — does NOT use 40-pin GPIO header. No pin conflicts with other HATs. |
| **KEYESTUDIO ReSpeaker 2-Mic Pi HAT V1** | WM8960 audio codec over I2S + I2C. 3× APA102 LEDs via SPI (MOSI=GPIO 10 / CLK=GPIO 11). Sits on 40-pin header. |
| **Geekworm X1202 PSU (4-cell 18650 UPS HAT)** | Battery management over I2C address 0x36 (MAX17043-compatible fuel gauge). Stacks below Pi. |
| **1.3" SH1106 OLED (I2C, 128×64)** | Controller is **SH1106**, NOT SSD1306. I2C address 0x3C. Wired to GPIO 2 (SDA) / GPIO 3 (SCL). |
| **3× Tactile buttons** | GPIO 17 (power/machine), GPIO 27 (action), GPIO 22 (interaction). All wire to GND; gpiozero internal pull-up active. |

### Key pin map

| GPIO | Function | Used by |
|---|---|---|
| 2 (SDA) | I2C bus | OLED (0x3C), WM8960 (0x1A), X1202 fuel gauge (0x36) |
| 3 (SCL) | I2C bus | (same bus, shared) |
| 10 (SPI0 MOSI) | APA102 data | ReSpeaker LEDs |
| 11 (SPI0 CLK) | APA102 clock | ReSpeaker LEDs |
| 18 (PCM_CLK) | I2S bit clock | ReSpeaker audio — **must NOT be used for SPI** |
| 19 (PCM_FS) | I2S LR clock | ReSpeaker audio |
| 20 (PCM_DIN) | I2S data in | ReSpeaker audio (mic) |
| 21 (PCM_DOUT) | I2S data out | ReSpeaker audio (speaker) |
| 5 | Button input | machine/power button (GPIO 17 is ReSpeaker HAT onboard — conflict) |
| 17 | ReSpeaker HAT onboard button | reserved — do not wire your power button here |
| 27 | Button input | action button |
| 22 | Button input | interaction button |

3rd-party add-ons load immediately: their agents and sub-agents are live in the system as soon as install completes, configurable per-agent from the web UI without restarting.

---

## Architecture (current branch: `claude/review-claude-md-f9B8r`)

### Layer overview (bottom-up)

```
~/.amini/  (user data: models + agent add-ons — separate from project source)
    ↓
Hardware (audio, LEDs, buttons, display, power, network)
    ↓
Model Layer (AmiPaths → registry → orchestrator → model wrappers)
    ↓
Sub-agent Layer (BaseSubAgent → ToolRegistry → FilteredToolRegistry per agent)
    ↓
Agent Layer (BaseAgent → built-ins + add-on agents, live enable/disable)
    ↓
Pipeline (VoicePipeline: listen → transcribe → respond → speak)
    ↓
cli.py / main.py (VoiceAssistant entry point)  +  DeviceServer (Flask, port 5000)
```

### Key files and their roles

| File | Purpose |
|---|---|
| `cli.py` | `amini` CLI — `run`, `install`, `list`, `remove`, `update`, `models`, `test` |
| `main.py` | `VoiceAssistant` class — wires all layers, runs wake loop on main thread |
| `config.yaml` | User-local runtime config (gitignored). Created from `config.yaml.default` on first run. |
| `config.yaml.default` | Committed template — models, device, agents, ally defaults |
| `core/config_manager.py` | `ConfigManager` — safe read/write with `EDITABLE_PATHS` whitelist; `ensure_config()` for first-run copy |
| `core/ami_paths.py` | `AmiPaths` — single source of truth for `~/.amini/`; path resolution for models and agents |
| `core/addon_installer.py` | `AddonInstaller` — preview + clone → validate → dep-check → test → install → seed config |
| `core/agent_manager.py` | `AgentManager` — loads built-ins + add-on plugins; live `enable_agent()` / `disable_agent()` / `update_equipped_sub_agents()` |
| `core/models/registry.py` | `ModelSpec` dataclass + `ModelRegistry(config, paths=None)` |
| `core/models/orchestrator.py` | `ModelOrchestrator` — lazy loading, Hailo slot enforcement, hot-swap |
| `core/pipeline.py` | `VoicePipeline` with 4 stages + `PipelineContext` dataclass |
| `agents/base_agent.py` | Abstract `BaseAgent(orchestrator, tool_registry)` — `process()` + `get_tools()` |
| `agents/base_sub_agent.py` | `BaseSubAgent(BaseTool)` ABC — `slug`, `display_name` attrs; `register_sub_agent()` |
| `agents/tools/base_tool.py` | `BaseTool` ABC + `ToolParam` dataclass + `to_llm_schema()` (Ollama format) |
| `agents/tools/tool_registry.py` | `ToolRegistry` — register, get, execute, all_schemas, sub-agent index. `FilteredToolRegistry` — per-agent live proxy filtered by equipped slugs |
| `agents/subagents/memory_subagent.py` | `MemorySubAgent` slug=`memory` — persistent key-value store |
| `agents/subagents/timer_subagent.py` | `TimerSubAgent` slug=`timer` — countdown timers with TTS |
| `agents/subagents/hardware_subagent.py` | `HardwareSubAgent` slug=`hardware` — battery, network, LED |
| `agents/subagents/updater_subagent.py` | `UpdaterSubAgent` slug=`updater` — plugin management |
| `agents/subagents/conversation_subagent.py` | `ConversationSubAgent` slug=`conversation` — history access |
| `agents/subagents/dependency_subagent.py` | `DependencySubAgent` slug=`dependency` — dep check/reconcile; works without orchestrator |
| `core/server/device_server.py` | Flask HTTP server (port 5000); starts when network is hotspot or wifi |
| `core/server/routes/config.py` | `/api/config/agents` — list + live toggle + sub-agent equip; `/api/config/device` — device settings |
| `core/server/routes/plugins.py` | `/api/plugins/*` — list, preview (async), install (async), remove, test |
| `core/server/routes/status.py` | `/api/status`, `/api/settings`, `/api/agents`, `/api/agent/cycle|set` |
| `core/server/routes/network.py` | `/api/network`, `/api/wifi/*` |
| `core/server/routes/conversations.py` | `/api/conversations*` |
| `core/server/routes/test_runner.py` | `/api/test/run`, `/api/test/jobs` |
| `core/server/templates/index.html` | Full SPA — Dashboard, Agents, WiFi, Plugins, Tests, History tabs |
| `requirements.in` | Human-maintained dependency list (edit this, then `pip-compile`) |
| `requirements.txt` | Compiled/pinned output of `requirements.in` |
| `tests/` | 400+ pytest unit tests covering all components |

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
    └── <name>/   3rd-party add-on packages (manifest.json + agents/ + sub_agents/)
```

---

## 3rd-Party Add-on Package Contract

Add-ons installed from GitHub into `~/.amini/agents/<name>/` support two layouts:

### Multi-agent package (preferred)

```
manifest.json           required   name, version, description, agents[], sub_agents[]
agents/                 required   one .py per agent listed in manifest
sub_agents/             optional   one .py per sub-agent listed in manifest
README.md               required   shown in web UI Preview before install
requirements.txt        optional   pip deps installed on install
tests/test_unit*.py     recommended  run pre-install (mocked)
tests/test_integration*.py  optional  run post-install
```

**`manifest.json` schema (multi-agent):**
```json
{
  "name": "my-addon",
  "version": "1.0.0",
  "description": "Short description shown in UI",
  "readme": "README.md",
  "requirements": "requirements.txt",
  "agents": [
    {
      "slug": "my_agent",
      "entry_class": "MyAgent",
      "file": "agents/my_agent.py",
      "display_name": "My Agent",
      "description": "What this agent does"
    }
  ],
  "sub_agents": [
    {
      "slug": "my_tool",
      "entry_class": "MyToolSubAgent",
      "file": "sub_agents/my_tool.py",
      "display_name": "My Tool",
      "description": "What this tool does"
    }
  ],
  "default_sub_agents": ["memory", "timer", "my_tool"]
}
```

### Legacy single-agent package (still supported, no changes required)

```
manifest.json    {name, version, entry_class, description}
agent.py         class extending BaseAgent with process() and get_tools()
requirements.txt (optional)
tests/           (optional)
```

### Install flow

```
amini install user/repo   (CLI)
  OR
Web UI → Plugins tab → enter user/repo → Preview → Install

Steps:
  1. git clone --depth=1
  2. Load + validate manifest.json
  3. Static-check agent files (process + get_tools present)
  4. Dependency pre-check via DependencySubAgent (warns, never aborts)
  5. Run pre-install unit tests (tests/ -k unit)
  6. Copy to ~/.amini/agents/<name>/
  7. pip install requirements.txt
  8. Post-install import check for all agent classes
  9. Run integration tests (tests/ -k integration) — warn on fail, don't abort
 10. Seed config.yaml: add agent slugs to agents.exposed + agents.config defaults
 11. → Agents are immediately active. No restart required.
```

### What "immediately active" means

After install:
- New agents appear in `GET /api/config/agents` and the Agents tab
- They are added to `agents.exposed` in `config.yaml`
- Their default sub-agent equip is seeded from `manifest.json → default_sub_agents`
- `AgentManager.enable_agent(slug)` is NOT called automatically at install — the user
  enables them from the Agents tab (or they appear in the next `amini run`)
- Sub-agent tools from `sub_agents/` are registered into the global `ToolRegistry`
  and become immediately equippable for any agent

---

## Agent + Sub-agent System

### Built-in agents

| Slug | Class | Description |
|---|---|---|
| `llm_response` | `LLMResponseAgent` | General Q&A, context-aware |
| `planning` | `PlanningAgent` | Multi-step reasoning, full tool access |
| `block_timer` | `BlockTimerAgent` | Focus timer (natural language → set_timer) |
| `family_scheduler` | `FamilySchedulerAgent` | Shared calendar |
| `shopping_list` | `ShoppingListAgent` | Shopping list management |
| `kids_story` | `KidsStoryAgent` | Kids' stories |
| `morning_briefing` | `MorningBriefingAgent` | Daily briefing |
| `family_intercom` | `FamilyIntercomAgent` | Family messaging |
| `ally` | `AllyAgent` | Autonomous companion, soul-aware (injected at runtime) |

### Built-in sub-agents (always registered, equippable per agent)

| Slug | Tools provided | Default for |
|---|---|---|
| `memory` | `memory_store`, `memory_recall` | most agents |
| `timer` | `set_timer`, `cancel_timer` | all agents |
| `conversation` | `get_conversation_history`, `summarize_conversation` | most agents |
| `hardware` | `get_battery_status`, `get_network_status`, `set_led_color` | planning |
| `updater` | `check_updates`, `install_agent`, `list_installed_agents` | planning |
| `dependency` | `check_requirements`, `list_installed`, `reconcile_requirements` | planning |

### Sub-agent equip config (in `config.yaml`)

```yaml
agents:
  config:
    planning:
      enabled: true
      equipped_sub_agents: [memory, timer, conversation, hardware, updater, dependency]
    block_timer:
      enabled: true
      equipped_sub_agents: [timer]
```

Changes via web UI (`POST /api/config/agents/<slug>/sub-agents`) take effect
**immediately** — `FilteredToolRegistry` is a live proxy, no restart needed.

### Writing a sub-agent for an add-on

```python
from agents.base_sub_agent import BaseSubAgent
from agents.tools.base_tool import BaseTool, ToolParam

class MyToolSubAgent(BaseSubAgent):
    slug = "my_tool"           # unique key used in equipped_sub_agents config
    display_name = "My Tool"   # shown in Agents tab UI
    name = "my_primary_tool"   # primary LLM-callable tool name
    description = "..."
    parameters = [ToolParam("arg", "string", "description", required=True)]

    def execute(self, arg: str) -> str:
        return f"result: {arg}"

    def get_additional_tools(self) -> list[BaseTool]:
        return [MySecondaryTool()]  # optional extra tools bundled with this sub-agent
```

---

## Web Server (port 5000)

Starts automatically when network state is `hotspot` or `wifi`. Provides a mobile-first
dark-theme SPA at `http://<device-ip>:5000`.

### Tabs and what users can do

| Tab | Capability |
|---|---|
| **Dashboard** | Battery, network, IP. Switch/cycle active agent. Toggle hotword. |
| **Agents** | See ALL agents (built-in + add-ons) with enable/disable toggles. See ALL sub-agents per agent with equip/unequip chips. Device settings (display timeout, hotspot, auto-update). |
| **WiFi** | Scan + connect to WiFi, manage saved networks, cycle network mode. |
| **Plugins** | Preview add-on before install (README + dep conflicts). Install from GitHub. Remove. Run tests. |
| **Tests** | Run full pytest suite or a specific agent's tests. View output live. |
| **History** | Browse conversation history, filter by agent. |

### Config API (what the server can write)

Only `EDITABLE_PATHS` keys are writable. Everything else is read-only from the UI.

```
agents.exposed           # which agents are in the cycling list
agents.config            # per-agent enabled + equipped_sub_agents
device.display_timeout_sec
device.hotspot_ssid
device.hotspot_password
device_server.port
auto_update.enabled
auto_update.channel
ally.threshold
ally.check_interval_sec
ally.interaction_mode
```

Hardware pins, model backends, Hailo paths → **always read-only from the server**.

---

## CLI Usage

```
amini run                        # start voice assistant (creates config.yaml on first run)
amini install user/repo          # install 3rd-party add-on from GitHub
amini list                       # list built-in + installed agents
amini remove <name>              # uninstall add-on
amini update <name> user/repo    # update installed add-on
amini models pull                # download/cache all configured models
amini models list                # show model paths and backends
amini test                       # run full project test suite
amini test <agent>               # run specific agent's tests
```

---

## Design decisions to remember

- **`config.yaml` is user-local; `config.yaml.default` is the committed template** — `ConfigManager.ensure_config()` copies default → config on first `amini run`. `config.yaml` is gitignored.
- **`ConfigManager.EDITABLE_PATHS` whitelist** — only approved config keys can be written via the server. Hardware pins, model backends, etc. are read-only from the web UI.
- **`FilteredToolRegistry` is a live proxy** — filters the global registry by equipped sub-agent slugs at call time. Equip changes take effect immediately; no agent restart needed.
- **Agent enable/disable is live** — `AgentManager.enable_agent()` / `disable_agent()` add/remove agents from the cycling list in-place. Sub-agent equip is also live via `update_equipped_sub_agents()`.
- **`DependencySubAgent` works without an orchestrator** — pass `orchestrator=None`; it only uses `packaging` + `subprocess`. Used by `AddonInstaller.preview()` and `install()`.
- **Preview gate for addon install** — web UI requires Preview to be loaded before Install activates. Shows README, agent/sub-agent list, and dependency conflicts.
- **Add-on packages support multi-agent layout** — `manifest.json` with `agents: [...]` and `sub_agents: [...]` keys. Legacy single-file `agent.py` repos still work unchanged.
- **Install seeds config.yaml** — `_seed_agent_config()` writes default equip for new agents so they're immediately configurable from the UI.
- **`requirements.in` is human-maintained; `requirements.txt` is compiled output** — run `pip-compile requirements.in` after adding deps (`pip-tools` in dev dependencies).
- **`AmiPaths` is the single source of truth for `~/.amini/`** — pass it to `ModelRegistry`, `AgentManager`, and `AddonInstaller`; never hardcode `~/.amini/` paths elsewhere.
- **`ModelRegistry(config, paths=None)`** — when `paths` is provided, `spec.path` is auto-resolved: `null` → role model dir, bare filename → role model dir / filename, absolute → unchanged. Backward compatible: `paths=None` preserves original behaviour.
- **`ModelRole` is the primary key** — `orchestrator.get(ModelRole.STT)` everywhere, never string lookups after registry parse.
- **`eager: true` in config** — VAD and WAKE load at startup; others load lazily on first use.
- **Hailo-10H is a single exclusive resource** — `ModelOrchestrator._hailo_slot_taken` flag prevents two Hailo models from loading simultaneously. `swap()` releases the slot.
- **`sst.py` not `stt.py`** — the STT wrapper file has a typo in its name; keep it as-is to avoid breaking imports.
- **Tool-calling uses Ollama's native format** — `to_llm_schema()` produces `{type: "function", function: {name, description, parameters}}` dicts; `chat_with_tools()` returns `(text, parsed_calls)`.
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

### Testing a specific installed add-on

```bash
amini test <agent-name>
# or directly:
python -m pytest ~/.amini/agents/<name>/tests/ -q
```

### Dependency management

```bash
# After adding a package to requirements.in:
pip-compile requirements.in
# Then commit both requirements.in and requirements.txt
```
