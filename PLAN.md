# Implementation Plan: Config Management, Agent/Sub-agent UI, Add-on Packages, Dependency Sub-agent

## Overview

Seven coherent changes that build on each other in strict dependency order. Each phase
is independently testable. No existing tests are broken; new tests cover all new paths.

---

## Phase 1 — `config.yaml.default` + First-Run Initialization

**Goal:** Repo ships a `config.yaml.default`. On first `amini run`, if no `config.yaml`
exists, it is copied from the default. The server can edit config "within reason" via a
validated `ConfigManager`.

### 1a. Create `config.yaml.default`
- Copy current `config.yaml` → `config.yaml.default` (committed to repo, never modified at runtime).
- Add a new `agents.config` section documenting per-agent sub-agent equip defaults (see Phase 3).
- `config.yaml` is **gitignored** (user-local). Add to `.gitignore`.

### 1b. `core/config_manager.py` (new file)
```python
class ConfigManager:
    def __init__(self, config_path: Path, default_path: Path)

    @classmethod
    def ensure_config(cls, config_path, default_path) -> None
        # If config_path doesn't exist, copy default_path → config_path
        # Print: "First run: created config.yaml from defaults. Visit http://... to customise."

    def get(self, *keys, default=None)          # dot-path lookup: get("device", "port")
    def set(self, value, *keys) -> None         # set value at path, validate, save atomically
    def reload(self) -> None                    # re-read from disk (used after external edits)
    def raw(self) -> dict                       # full config as dict (read-only copy)

    # Validation: only allow changes to pre-approved keys
    EDITABLE_PATHS: set[tuple] = {
        ("device", "display_timeout_sec"),
        ("device", "hotspot_ssid"),
        ("device", "hotspot_password"),
        ("device_server", "port"),
        ("auto_update", "enabled"),
        ("auto_update", "channel"),
        ("agents", "exposed"),
        ("agents", "config"),    # entire sub-tree
        ("ally", "threshold"),
        ("ally", "check_interval_sec"),
        ("ally", "interaction_mode"),
    }
```

- Atomic save: write to `.tmp` then `rename` (same pattern as `AmiPaths.save_settings`).
- `ConfigManager` is instantiated once in `VoiceAssistant.__init__` and passed to
  `DeviceServer` via `app.config["CONFIG_MANAGER"]`.

### 1c. `cli.py` — first-run check
In the `run` command, before constructing `VoiceAssistant`:
```python
ConfigManager.ensure_config(config_path, default_path)
```

### 1d. `main.py` — use ConfigManager
Replace `yaml.safe_load(open("config.yaml"))` with `ConfigManager(config_path, default_path)`.
All internal `self.config.get(...)` calls remain identical (same dict interface).

---

## Phase 2 — Sub-agent Metadata

**Goal:** Each sub-agent knows its own slug, display name, and description so the server
can enumerate them without hardcoding anything.

### 2a. Add class attributes to `BaseSubAgent`
```python
class BaseSubAgent(BaseTool, ABC):
    slug: str = ""               # machine key: "memory", "timer", "hardware", etc.
    display_name: str = ""       # human label shown in UI
    description: str = ""        # one-line description for UI
```

### 2b. Update each sub-agent in `agents/subagents/`
Add `slug`, `display_name`, `description` to:
- `MemorySubAgent`     → slug="memory"
- `TimerSubAgent`      → slug="timer"
- `HardwareSubAgent`   → slug="hardware"
- `UpdaterSubAgent`    → slug="updater"
- `ConversationSubAgent` → slug="conversation"
- Ally sub-agents      → slug="ally_memory", "soul_update"

### 2c. `register_sub_agent` — index by slug
Update `register_sub_agent` (and `ToolRegistry`) to also maintain a
`slug → BaseSubAgent` index so the server can list available sub-agents by slug.

```python
# ToolRegistry additions:
def list_sub_agents(self) -> list[BaseSubAgent]   # all registered sub-agents
def get_sub_agent(slug: str) -> BaseSubAgent | None
```

---

## Phase 3 — Agent Configuration: Enable/Disable + Sub-agent Equip

**Goal:** config.yaml tracks which agents are enabled and which sub-agents are
equipped per-agent. `AgentManager` and agents respect this at runtime.

### 3a. `config.yaml.default` — `agents.config` section
```yaml
agents:
  exposed:
    - llm_response
    - planning
    - block_timer

  # Per-agent config: enabled flag + equipped sub-agents
  config:
    llm_response:
      enabled: true
      equipped_sub_agents: [memory, timer, conversation]
    planning:
      enabled: true
      equipped_sub_agents: [memory, timer, conversation, hardware, updater]
    block_timer:
      enabled: true
      equipped_sub_agents: [timer]
    family_scheduler:
      enabled: true
      equipped_sub_agents: [memory, conversation]
    shopping_list:
      enabled: true
      equipped_sub_agents: [memory, conversation]
    kids_story:
      enabled: true
      equipped_sub_agents: [memory]
    morning_briefing:
      enabled: true
      equipped_sub_agents: [memory, conversation]
    family_intercom:
      enabled: true
      equipped_sub_agents: [memory, conversation]
```

### 3b. `ToolRegistry.filtered_for(slug, config_manager)` (new method)
Returns a lightweight proxy `FilteredToolRegistry` that only exposes tools whose
sub-agent slug is in the `equipped_sub_agents` list for `slug`. Falls back to all
tools if no config entry exists (backward-compatible).

```python
class FilteredToolRegistry(ToolRegistry):
    """Wraps a ToolRegistry and exposes only equipped sub-agent tools."""
    def __init__(self, registry: ToolRegistry, allowed_slugs: set[str])
    # get(), execute(), all_schemas() delegate to parent, filtered by allowed_slugs
```

### 3c. `AgentManager` — respects enable flag + passes filtered registry
- `AgentManager.__init__` accepts `config_manager` (optional, backward-compat).
- When building the `exposed` slugs list, exclude agents where `config.enabled == false`.
- When loading an agent, pass `FilteredToolRegistry` instead of the global registry.
- Add `get_all_agent_metadata() -> list[dict]` — returns ALL known agents (built-in + installed)
  with `{slug, display_name, description, enabled, equipped_sub_agents, source}` shape.

### 3d. `VoiceAssistant` — passes config_manager to AgentManager
```python
self.agent_manager = AgentManager(
    slugs=exposed_slugs,
    orchestrator=self.orchestrator,
    tool_registry=self.tool_registry,
    paths=self.paths,
    context=self.context,
    config_manager=self.config_manager,   # NEW
)
```

---

## Phase 4 — Config & Agent API Routes

**Goal:** The server exposes safe read/write endpoints for config + agent management.

### 4a. `core/server/routes/config.py` (new file)
```
GET  /api/config/agents
    → {agents: [{slug, display_name, description, enabled, source,
                 equipped_sub_agents: [{slug, display_name, equipped}]}]}
    # "source": "builtin" | "addon"
    # equipped_sub_agents: all registered sub-agents, each with current equip state

POST /api/config/agents/<slug>/toggle
    body: {enabled: bool}
    → 200 {slug, enabled}  |  404

POST /api/config/agents/<slug>/sub-agents
    body: {equipped_sub_agents: ["memory", "timer"]}
    → 200 {slug, equipped_sub_agents}

GET  /api/config/device
    → {display_timeout_sec, hotspot_ssid, hotspot_password,
       device_server_port, auto_update_enabled, auto_update_channel}

POST /api/config/device
    body: any subset of the above keys
    → 200 updated values  |  400 {error, invalid_keys}
```

### 4b. Wire blueprint in `device_server.py`
```python
from core.server.routes.config import bp as config_bp
app.register_blueprint(config_bp)
```

---

## Phase 5 — "Agents" Tab in Web UI

**Goal:** A new Agents tab in the dashboard showing the full agent hierarchy,
with enable/disable toggles for agents and per-agent sub-agent equip toggles.

### 5a. `core/server/templates/index.html` — add Agents tab
New tab button between Dashboard and Plugins:
```html
<button class="tab-btn" onclick="showTab('agents')" id="tab-agents">Agents</button>
```

New panel `#panel-agents` with two sections:

**Built-in Agents** (always present):
```
[ ◆ llm_response ]  [enabled ●]
  ▸ Sub-agents: [memory ●] [timer ●] [conversation ●] [hardware ○] [updater ○]

[ ◆ planning ]      [enabled ●]
  ▸ Sub-agents: [memory ●] [timer ●] [conversation ●] [hardware ●] [updater ●]
...
```

**Add-on Agents** (from ~/.amini/agents/):
- Same card layout but with "Add-on" badge and Remove button.

Behaviour:
- Toggle agent → `POST /api/config/agents/<slug>/toggle`
- Toggle sub-agent chip → `POST /api/config/agents/<slug>/sub-agents` (debounced 500ms)
- Active agent (from `/api/status`) shown with accent border.
- Disabled agents are greyed out. If the current agent is disabled, the UI warns.

### 5b. `core/server/static/app.css` — styles
Add: `.sub-agent-chip`, `.sub-agent-chip.equipped`, `.agent-card.disabled`,
     `.badge-addon`, `.badge-builtin`, toggle animation classes.

---

## Phase 6 — Add-on Package Structure & Updated Installer

**Goal:** Add-on repos can now ship multiple agents AND sub-agents in a structured
package. The installer handles the new layout while remaining backward-compatible
with single-agent `agent.py` repos.

### 6a. Extended `manifest.json` schema
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
      "description": "What this tool provides"
    }
  ]
}
```

**Backward-compat:** If `agents` key is absent but `entry_class` + `agent.py` exist,
the old single-agent path is used automatically.

### 6b. `AddonInstaller` updates (`core/addon_installer.py`)

New detection logic in `install()`:
```
if manifest has "agents" list:
    → multi-agent package path
    → validate each agents/<file>.py for process() + get_tools()
    → validate each sub_agents/<file>.py for execute()
    → run pre-install tests
    → copy entire package to ~/.amini/agents/<name>/
    → pip install requirements.txt
    → run post-install import check for each agent + sub-agent
    → update config.yaml agents.config with defaults for each new agent
else:
    → legacy single-agent path (unchanged)
```

New `preview(source) -> dict` method (used by web UI before install):
```python
def preview(self, source: str) -> dict:
    """Clone to temp dir, return manifest + README text without installing."""
    # Returns: {manifest, readme_text, requirements_text, dependency_conflicts: [...]}
    # dependency_conflicts populated by DependencySubAgent.check_addon_deps()
```

New `GET /api/plugins/preview` route wrapping `preview()` as an async job.

### 6c. Plugin UI updates (Plugins tab)
- "Install Plugin" form: after entering source, "Preview" button calls `/api/plugins/preview`.
- Preview modal shows: description, agents list, sub-agents list, README excerpt,
  dependency conflicts (if any) as coloured warnings.
- "Install" button only active after preview; shows warnings inline.

---

## Phase 7 — `DependencySubAgent`

**Goal:** A built-in sub-agent that reconciles an add-on's `requirements.txt`
against this project's requirements. Used by the installer and exposed as an LLM tool.

### 7a. `agents/subagents/dependency_subagent.py` (new file)

```python
class DependencySubAgent(BaseSubAgent):
    slug = "dependency"
    display_name = "Dependency Manager"
    description = "Checks and reconciles Python package requirements"

    name = "check_requirements"
    description = "Check addon requirements against installed packages"
    parameters = [
        ToolParam("requirements_text", str, "requirements.txt content to check"),
    ]

    def execute(self, requirements_text: str) -> str:
        # Parse requirements_text with packaging.requirements.Requirement
        # For each package: check pip show, compare version specifiers
        # Return JSON: {ok: [...], conflicts: [{pkg, wanted, installed}], new: [...]}

    def get_additional_tools(self) -> list[BaseTool]:
        return [
            _ListInstalledTool(),    # list_installed() → current pip packages
            _ReconcileTool(self),    # reconcile_requirements(text) → merged requirements
        ]
```

Internal helpers (private classes in same file):
- `_ListInstalledTool` — runs `pip list --format=json`, returns package table.
- `_ReconcileTool` — merges two requirements.txt texts, resolves version conflicts
  using `packaging.version` to choose the tighter constraint; flags true incompatibilities.

### 7b. Register `DependencySubAgent` in `main.py`
```python
from agents.subagents.dependency_subagent import DependencySubAgent
register_sub_agent(tool_registry, DependencySubAgent(self.orchestrator, self.paths))
```

Default equip: all agents that should have access to it get `dependency` in their
`equipped_sub_agents` list. Default: only `planning` gets it equipped.

### 7c. `AddonInstaller` uses `DependencySubAgent`
In `preview()` and `install()`, instantiate `DependencySubAgent` directly
(without an orchestrator — it doesn't need one) and call `.execute()`:
```python
dep = DependencySubAgent(orchestrator=None, paths=self._paths)
conflict_report = dep.execute(requirements_text)
```

### 7d. Requirements maintenance for this repo
- Rename `requirements.txt` → `requirements.in` (source of truth, human-maintained).
- Add `pip-tools` to dev dependencies.
- Add `requirements.txt` as compiled/pinned output (generated by `pip-compile`).
- Add `amini models pull` step in `cli.py` that calls `pip-sync requirements.txt`
  to ensure the environment is in sync.
- Document in CLAUDE.md: "Run `pip-compile requirements.in` after adding deps."

---

## File Change Summary

| File | Action |
|---|---|
| `config.yaml.default` | **CREATE** from config.yaml + agents.config section |
| `config.yaml` | Add to `.gitignore` |
| `core/config_manager.py` | **CREATE** — safe config read/write |
| `core/agent_manager.py` | **MODIFY** — accept config_manager, filter by enabled, use FilteredToolRegistry |
| `agents/tools/tool_registry.py` | **MODIFY** — add sub-agent index + filtered_for() |
| `agents/base_sub_agent.py` | **MODIFY** — add slug, display_name, description class attrs |
| `agents/subagents/*.py` (5 files) | **MODIFY** — add slug/display_name/description to each |
| `agents/subagents/dependency_subagent.py` | **CREATE** — DependencySubAgent |
| `core/addon_installer.py` | **MODIFY** — multi-agent package support + preview() |
| `core/server/device_server.py` | **MODIFY** — register config blueprint, pass config_manager |
| `core/server/routes/config.py` | **CREATE** — agent toggle + sub-agent equip + device settings |
| `core/server/routes/plugins.py` | **MODIFY** — add /api/plugins/preview endpoint |
| `core/server/templates/index.html` | **MODIFY** — add Agents tab, update Plugins tab |
| `core/server/static/app.css` | **MODIFY** — styles for new components |
| `main.py` | **MODIFY** — use ConfigManager, register DependencySubAgent |
| `cli.py` | **MODIFY** — first-run config copy |
| `requirements.in` | **CREATE** (rename from requirements.txt) |
| `requirements.txt` | Becomes compiled/pinned output |
| `tests/test_config_manager.py` | **CREATE** |
| `tests/test_dependency_subagent.py` | **CREATE** |
| `tests/test_addon_installer.py` | **MODIFY** — cover multi-agent + preview() |

---

## Design Decisions

1. **`ConfigManager.EDITABLE_PATHS` whitelist** — server can only write pre-approved
   config keys. Hardware pins, model backends, etc. are read-only from the server.
   This prevents the web UI from bricking the device.

2. **`FilteredToolRegistry` is a thin proxy** — it doesn't copy tools; it delegates
   to the global registry and filters at call time. If a sub-agent is later equipped,
   the change is immediately visible without reloading.

3. **Backward-compat for add-ons** — old single-file `agent.py` repos still work.
   New multi-agent packages are detected by the presence of an `agents/` key in `manifest.json`.

4. **`DependencySubAgent` works without an orchestrator** — its tools only use `packaging`
   and `subprocess`, not models. Pass `orchestrator=None` when calling from the installer.

5. **`pip-tools` discipline** — `requirements.in` is human-maintained; `requirements.txt`
   is compiled and pinned. Addon deps are pip-installed into the environment directly
   (as today), but `DependencySubAgent` warns about conflicts before they happen.

6. **No agent reload at runtime** — enabling/disabling an agent or equipping a sub-agent
   writes to config.yaml and takes effect on next `amini run`. The web UI shows a
   "Restart required" banner when a restart-requiring change is made. Settings-only
   changes (hotword, device settings) take effect immediately.

---

## Implementation Order (strict)

```
Phase 1  → Phase 2  → Phase 3  → Phase 4  → Phase 5
                            ↓
                         Phase 7 → Phase 6
```

Phase 7 (DependencySubAgent) must exist before Phase 6 (installer can call it).
All other phases are linear.
