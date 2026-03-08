# mobile-ami — Claude Memory

## Project Goal

**mobile-ami** is a handheld, fully offline voice AI assistant running on a Raspberry Pi with a Hailo-10H AI accelerator HAT. The device runs 5 AI models locally (STT, TTS, LLM, wake word, VAD) and supports multiple specialized agents that the user can cycle through via a physical button.

---

## Architecture (as of current branch: `claude/voice-ai-orchestration-IQSl9`)

### Layer overview (bottom-up)

```
Hardware (audio, LEDs, buttons, display, power, network)
    ↓
Model Layer (registry → orchestrator → model wrappers)
    ↓
Tool Layer (BaseTool, ToolRegistry, TimerTool)
    ↓
Agent Layer (BaseAgent → QAAgent / BlockTimerAgent)
    ↓
Pipeline (VoicePipeline: listen → transcribe → respond → speak)
    ↓
main.py (VoiceAssistant entry point)
```

### Key files and their roles

| File | Purpose |
|---|---|
| `main.py` | `VoiceAssistant` class — wires all layers, runs wake loop on main thread |
| `config.yaml` | All model config (name, backend, quant, path, version, eager) |
| `core/model_registry.py` | `ModelSpec` dataclass + `ModelRegistry` (pure data, no loading). Enums: `ModelRole`, `Backend`, `QuantType` |
| `core/model_orchestrator.py` | `ModelOrchestrator` — lazy loading, Hailo slot enforcement, hot-swap via `swap()`, `preload_eager()` |
| `core/pipeline.py` | `VoicePipeline` with 4 stages + `PipelineContext` dataclass |
| `core/sst.py` | faster-whisper STT wrapper (note: filename is `sst.py`, not `stt.py`) |
| `core/tts.py` | Piper TTS wrapper |
| `core/llm.py` | Ollama LLM wrapper — `query()`, `chat()`, `chat_with_tools()` |
| `core/vad.py` | WebRTC VAD wrapper |
| `core/wake_detector.py` | OpenWakeWord wrapper |
| `core/agent_manager.py` | Manages named agents, tracks active agent, supports `cycle()` |
| `agents/base_agent.py` | Abstract `BaseAgent(orchestrator, tool_registry)` — `process()` + `get_tools()` |
| `agents/qa_agent.py` | General Q&A with agentic tool loop (max 5 rounds) |
| `agents/block_timer_agent.py` | Focus timer — LLM parses natural language, calls `set_timer` tool |
| `agents/tools/base_tool.py` | `BaseTool` ABC + `ToolParam` dataclass + `to_llm_schema()` (Ollama format) |
| `agents/tools/tool_registry.py` | `ToolRegistry` — register, get, execute, all_schemas |
| `agents/tools/timer_tool.py` | `TimerTool` — starts background thread timer, speaks start/complete via injected callback |
| `tests/` | 85 pytest unit tests covering all above components |

---

## Design decisions to remember

- **`ModelRole` is the primary key** — `orchestrator.get(ModelRole.STT)` everywhere, never string lookups after registry parse.
- **`eager: true` in config** — VAD and WAKE load at startup; others load lazily on first use.
- **Hailo-10H is a single exclusive resource** — `ModelOrchestrator._hailo_slot_taken` flag prevents two Hailo models from loading simultaneously. `swap()` releases the slot.
- **`sst.py` not `stt.py`** — the STT wrapper file has a typo in its name; keep it as-is to avoid breaking imports.
- **Tool-calling uses Ollama's native format** — `to_llm_schema()` produces OpenAI-compatible dicts; `chat_with_tools()` returns `(text, parsed_calls)`.
- **`BlockTimerAgent` gets TTS from orchestrator in `get_tools()`** — so `TimerTool.on_speak` always has a live TTS instance even after a hot-swap.
- **Tests mock all hardware/library deps** — tests run without any Raspberry Pi hardware, Ollama, Whisper, etc. installed.

---

## What was built in this session

The voice AI orchestration overhaul added:
1. `core/model_registry.py` — typed model manifests replacing raw config dicts
2. `core/model_orchestrator.py` — central lifecycle manager with Hailo enforcement
3. `core/pipeline.py` — explicit 4-stage pipeline replacing ad-hoc flow in main.py
4. `agents/tools/` — tool system (BaseTool, ToolRegistry, TimerTool)
5. `agents/base_agent.py` — abstract base with `get_tools()` hook
6. `agents/qa_agent.py` — agentic tool-calling loop
7. `agents/block_timer_agent.py` — LLM-driven timer via tools
8. `tests/` — 85 unit tests (added in follow-up commit)
9. `requirements.txt` — added `pytest`
10. `.gitignore` — added `__pycache__` / `.pyc` exclusions

---

## Hailo integration status

Hailo-10H is **wired but not yet active**. The `Backend.HAILO` enum and `_hailo_slot_taken` enforcement exist. To activate:
- Set `backend: hailo` and `path: /path/to/model.hef` for a role in `config.yaml`
- Add a `HailoSTT` (or similar) wrapper class
- Add a branch in `model_orchestrator._build_instance()` for `spec.backend == Backend.HAILO`

---

## Running tests

```bash
python -m pytest tests/ -q
```

No hardware required — all external deps are mocked.
