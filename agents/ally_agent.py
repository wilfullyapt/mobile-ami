"""
AllyAgent — the device's autonomous owner companion.

The Ally is architecturally distinct from all other agents:

1. It always reads SOUL.md before generating a response, giving it a stable
   identity, memory of its purpose, and awareness of its owner.

2. It operates in one of two states depending on whether an owner has been
   established:

   SEARCHING state (no owner):
     The ally introduces itself warmly and tries to discover who it belongs to.
     When someone claims ownership ("I am Jake, this is my device"), it fires
     the on_owner_established callback so main.py can persist the bond, create
     SOUL.md, and enroll the speaker's voice profile.

   SERVING state (owner known):
     The ally knows its owner by name and voice. It tracks when the owner
     last spoke, maintains ambient context from AllyListener, and proactively
     promotes the owner — offering encouragement, insight, or help.

3. Two invocation paths:

   process(text, speaker)         — explicit user interaction via pipeline
   should_intervene(threshold)    — autonomous decision: should I speak now?

Owner establishment flow:
  User says → "I am Alice, this device is mine"
  AllyAgent detects → fires on_owner_established("Alice")
  main.py → OwnerManager.establish("Alice") + SoulManager.create_for_owner(...)
           + VoiceProfileManager.enroll("Alice", audio, encoder)
"""

import logging
import re
import threading
import wave
from typing import Callable, Optional

import numpy as np

from agents.base_agent import BaseAgent
from core.model_registry import ModelRole

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ownership claim detection patterns
# ---------------------------------------------------------------------------

_OWNER_CLAIM_PATTERNS = [
    r"\bi am (\w+)[,.]?\s+(this (device|assistant) is mine|i own (this|you)|this belongs to me)\b",
    r"\bthis (device|assistant) (is mine|belongs to me)\b",
    r"\b(register me|i am the owner|set me as (the )?owner|make me (the )?owner)\b",
    r"\bi am your owner\b",
    r"\bmy name is (\w+)[,.]?\s+(this (device|assistant) is mine)\b",
]

# ---------------------------------------------------------------------------
# System prompt templates
# ---------------------------------------------------------------------------

_SEARCHING_SYSTEM = """\
{soul}

---
You are Ami in SEARCHING mode. You do not yet know who your owner is.
Your mission right now is to find your person and establish the bond.

Guidelines:
- Introduce yourself briefly and warmly when you initiate.
- If someone is talking, gently ask who they are.
- If someone claims ownership, respond warmly and guide them to say:
  "I am [name], this device is mine" so you can formally establish the bond.
- Keep every response under 40 words. Be inviting, never pushy.
"""

_SERVING_SYSTEM = """\
{soul}

---
You are Ami in SERVING mode. Your owner is {owner_name}.
{owner_context}

Recent ambient context (what you've been hearing):
{context_summary}

Guidelines:
- Address your owner by name when natural.
- Promote, encourage, and support {owner_name} based on what you know.
- Be warm, concise, and genuinely helpful. Under 60 words.
"""

_INTERVENE_PROMPT = """\
{soul}

---
You are Ami. Your owner is {owner_name}.
{owner_context}

You have been passively listening. Here is what you've heard recently:
{context_summary}

Should you speak up right now? Consider:
- Would speaking add genuine value?
- Is the timing appropriate?
- Are you promoting or helping your owner?

Reply with EXACTLY one of these formats:
  SPEAK: [your message — under 40 words]
  SILENT

Choose SILENT unless you have something genuinely useful to say.
"""

_SEARCHING_INTERVENE_PROMPT = """\
{soul}

---
You are Ami in SEARCHING mode. You haven't found your owner yet.
You heard this recently: {context_summary}

Should you gently introduce yourself to try to find your owner?
Reply SPEAK: [message] or SILENT. Keep any message under 30 words.
"""


# ---------------------------------------------------------------------------
# AllyAgent
# ---------------------------------------------------------------------------

class AllyAgent(BaseAgent):
    """
    The device's autonomous owner companion.

    Constructed in main.py with extra dependencies injected after the
    standard BaseAgent.__init__() via inject_ally_deps().
    """

    def __init__(
        self,
        orchestrator,
        tool_registry,
        paths=None,
        soul_manager=None,
        owner_manager=None,
        on_owner_established: Optional[Callable[[str], None]] = None,
        ally_listener=None,
        voice_profiles=None,
        ally_config: Optional[dict] = None,
    ):
        super().__init__(orchestrator, tool_registry, paths)
        self._soul = soul_manager
        self._owner = owner_manager
        self._on_owner_established = on_owner_established
        self._listener = ally_listener  # Optional[AllyListener]
        self._voice_profiles = voice_profiles
        self._ally_config = ally_config or {}

        # Internal sub-agents (NOT in global ToolRegistry)
        self._soul_sub = None
        self._memory_sub = None
        if soul_manager is not None:
            from agents.subagents.ally.soul_update_subagent import SoulUpdateSubAgent
            self._soul_sub = SoulUpdateSubAgent(orchestrator, soul_manager)
        if paths is not None:
            from agents.subagents.ally.memory_write_subagent import AllyMemoryWriteSubAgent
            self._memory_sub = AllyMemoryWriteSubAgent(orchestrator, paths)

        # Voice ID state
        self._pending_voice_id: list = []  # list[tuple[str, np.ndarray]]
        self._awaiting_voice_name: bool = False
        self._voice_id_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_exit(self, context=None) -> None:
        """Reset voice ID state when leaving ally mode or switching agents."""
        self._awaiting_voice_name = False

    # ------------------------------------------------------------------
    # Standard agent interaction (called by pipeline)
    # ------------------------------------------------------------------

    def process(self, text: str, speaker: Optional[str] = None, context=None) -> str:
        """
        Handle an explicit user interaction.

        If the device has no owner, checks whether the user is claiming
        ownership and fires on_owner_established if so.
        """
        # --- Voice ID state machine ---
        if self._awaiting_voice_name:
            name = self._extract_name_from_reply(text)
            with self._voice_id_lock:
                if name and self._pending_voice_id:
                    clip_path, clip_audio = self._pending_voice_id.pop(0)
                    if (
                        self._voice_profiles is not None
                        and self._orchestrator.has(ModelRole.SPEAKER)
                    ):
                        try:
                            encoder = self._orchestrator.get(ModelRole.SPEAKER)
                            self._voice_profiles.enroll(name, clip_audio, encoder, role="guest")
                        except Exception as exc:
                            logger.warning("AllyAgent: voice enroll failed: %s", exc)
            self._awaiting_voice_name = False
            return f"Got it, I'll remember {name or 'that person'}'s voice."

        if (
            self._pending_voice_id
            and self._ally_config.get("replay_unknown_voices", True)
            and self._owner_is_present()
        ):
            with self._voice_id_lock:
                if self._pending_voice_id:
                    clip_path, clip_audio = self._pending_voice_id[0]
                    self._play_audio_clip(clip_audio)
                    self._awaiting_voice_name = True
                    return "I heard someone I don't recognise. Who is this person?"

        # --- Ownership establishment ---
        if not self._is_owner_established:
            claimed = self._extract_owner_claim(text, speaker)
            if claimed:
                if self._on_owner_established:
                    self._on_owner_established(claimed)
                return (
                    f"I'm so glad to meet you, {claimed}. "
                    "You are now my owner. I'm here to support and promote you. "
                    "Can you tell me your purpose — what should I help you with most?"
                )

        # --- Record owner presence ---
        if speaker and self._owner and speaker == self._owner.owner_name:
            self._owner.record_seen(speaker)

        soul = self._soul_text
        llm = self._orchestrator.get(ModelRole.LLM)

        if not self._is_owner_established:
            system = _SEARCHING_SYSTEM.format(soul=soul)
        else:
            system = _SERVING_SYSTEM.format(
                soul=soul,
                owner_name=self._owner.owner_name,
                owner_context=self._owner_context_line,
                context_summary=self._context_summary or "No recent ambient context.",
            )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]
        response = llm.chat(messages)
        return response or self._fallback_response()

    # ------------------------------------------------------------------
    # Ally mode — interval_listen + daily_update
    # ------------------------------------------------------------------

    def interval_listen(self, notes: list, context=None) -> Optional[str]:
        """
        Review the latest ambient notes and optionally speak.

        Called every check_interval_sec by the _on_ally_context_ready callback
        in main.py.  Returns a spoken message string or None to stay silent.
        """
        if not notes:
            return None

        soul = self._soul_text
        owner_name = self._owner.owner_name if self._owner else "your owner"
        duration_min = int(
            sum(
                (n.chunk_end - n.chunk_start).total_seconds()
                for n in notes
            ) / 60
        )
        notes_text = "\n\n---\n\n".join(n.formatted_text() for n in notes)

        internal_tools = [
            sub.to_llm_schema()
            for sub in [self._soul_sub, self._memory_sub]
            if sub is not None
        ]

        system = f"{soul}\n\n---\nYou are Ami, the device companion for {owner_name}."
        user = (
            f"You've been listening for the past {duration_min} minute(s). "
            f"Here is what you heard:\n\n{notes_text}\n\n"
            "Should you speak up? You may also update your memory or soul via tools. "
            "Reply SPEAK:[message] or SILENT."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        final_text = self._tool_loop(messages, internal_tools, max_rounds=5)

        # Queue unknown voices for identification on next owner interaction
        if self._ally_config.get("replay_unknown_voices", True):
            for note in notes:
                for clip_path in note.unknown_clip_paths:
                    clip_audio = self._load_clip_audio(clip_path)
                    if clip_audio is not None:
                        with self._voice_id_lock:
                            self._pending_voice_id.append((clip_path, clip_audio))

        if final_text and final_text.strip().upper().startswith("SPEAK:"):
            msg = final_text.strip()[len("SPEAK:"):].strip()
            logger.info("AllyAgent interval_listen: speaking: %s", msg[:60])
            return msg

        logger.debug("AllyAgent interval_listen: staying silent")
        return None

    def daily_update(self, context=None) -> None:
        """
        Called once per day (via EvalDay) to review notes and update soul/memory.
        """
        from datetime import date
        import json

        today_str = date.today().isoformat()
        today_prefix = today_str.replace("-", "")

        notes_texts: list[str] = []
        if self._paths is not None:
            notes_dir = self._paths.ally_notes_dir
            if notes_dir.exists():
                for note_file in sorted(notes_dir.glob(f"{today_prefix}*.json")):
                    try:
                        from core.ambient_note import AmbientNote
                        note = AmbientNote.from_json(note_file.read_text())
                        notes_texts.append(note.formatted_text())
                    except Exception as exc:
                        logger.warning("AllyAgent daily_update: bad note %s: %s", note_file, exc)

        mem_text = ""
        if self._paths is not None:
            mem_file = self._paths.memory_dir / f"{today_str}.json"
            if mem_file.exists():
                try:
                    mem_data = json.loads(mem_file.read_text())
                    mem_text = mem_data.get("summary", "")
                except Exception:
                    pass

        owner_name = self._owner.owner_name if self._owner else "your owner"
        soul = self._soul_text
        notes_block = "\n\n---\n\n".join(notes_texts) or "(no ambient notes today)"

        internal_tools = [
            sub.to_llm_schema()
            for sub in [self._soul_sub, self._memory_sub]
            if sub is not None
        ]

        system = f"{soul}\n\n---\nYou are Ami. Today is {today_str}."
        user = (
            f"Review your day as {owner_name}'s ally.\n\n"
            f"Ambient notes:\n{notes_block}\n\n"
            f"Conversation summary:\n{mem_text or '(none)'}\n\n"
            "Update your soul and memories via tools as appropriate."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        self._tool_loop(messages, internal_tools, max_rounds=8)
        logger.info("AllyAgent daily_update: complete for %s", today_str)

    # ------------------------------------------------------------------
    # Autonomous intervention decision
    # ------------------------------------------------------------------

    def should_intervene(
        self,
        threshold: float = 0.6,
        context_override: Optional[list] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Evaluate whether the ally should autonomously speak up.

        Returns (True, message) to speak, (False, None) to stay silent.

        The LLM is the primary decision-maker (SPEAK vs SILENT format).
        ``threshold`` is reserved for future numeric confidence scoring.
        ``context_override`` allows tests/callers to inject a context list
        directly without an AllyListener being wired in.
        """
        soul = self._soul_text
        llm = self._orchestrator.get(ModelRole.LLM)

        context = context_override if context_override is not None else self._listener_context
        summary = self._format_context(context)

        if not self._is_owner_established:
            if not summary:
                return False, None  # Nothing heard; don't initiate in silence
            prompt = _SEARCHING_INTERVENE_PROMPT.format(
                soul=soul,
                context_summary=summary,
            )
            messages = [{"role": "user", "content": prompt}]
            response = llm.chat(messages)
            if response and response.strip().upper().startswith("SPEAK:"):
                msg = response.strip()[len("SPEAK:"):].strip()
                logger.info("AllyAgent (searching): elects to speak: %s", msg[:60])
                return True, msg
            return False, None

        prompt = _INTERVENE_PROMPT.format(
            soul=soul,
            owner_name=self._owner.owner_name,
            owner_context=self._owner_context_line,
            context_summary=summary or "Nothing heard recently.",
        )
        messages = [{"role": "user", "content": prompt}]
        response = llm.chat(messages)

        if response and response.strip().upper().startswith("SPEAK:"):
            msg = response.strip()[len("SPEAK:"):].strip()
            logger.info("AllyAgent (serving): elects to speak: %s", msg[:60])
            return True, msg

        logger.debug("AllyAgent: elects to stay silent")
        return False, None

    # ------------------------------------------------------------------
    # Helpers / properties
    # ------------------------------------------------------------------

    @property
    def _is_owner_established(self) -> bool:
        return self._owner is not None and self._owner.has_owner

    @property
    def _soul_text(self) -> str:
        if self._soul:
            return self._soul.read(has_owner=self._is_owner_established)
        return ""

    @property
    def _owner_context_line(self) -> str:
        if not self._owner:
            return ""
        secs = self._owner.seconds_since_owner_seen()
        if secs is None:
            return f"You have not yet heard {self._owner.owner_name} speak since startup."
        if secs < 60:
            return f"{self._owner.owner_name} spoke less than a minute ago."
        if secs < 3600:
            return f"{self._owner.owner_name} was last heard {int(secs / 60)} minute(s) ago."
        return f"{self._owner.owner_name} was last heard {int(secs / 3600)} hour(s) ago."

    @property
    def _context_summary(self) -> str:
        return self._format_context(self._listener_context)

    @property
    def _listener_context(self) -> list:
        if self._listener is None:
            return []
        return self._listener.get_recent_context()

    def _format_context(self, context: list) -> str:
        if not context:
            return ""
        lines = []
        for u in context[-12:]:  # last 12 utterances max
            ago = int(u.seconds_ago())
            who = u.speaker or "unknown"
            owner_tag = " [owner]" if u.is_owner else ""
            lines.append(f"[{ago}s ago, {who}{owner_tag}]: {u.text}")
        return "\n".join(lines)

    def _extract_owner_claim(self, text: str, speaker: Optional[str]) -> Optional[str]:
        """
        Detect an ownership claim in text. Returns the claimed display name
        or None. Prefers the voice-identified speaker name for reliability.
        """
        lowered = text.lower()
        for pattern in _OWNER_CLAIM_PATTERNS:
            m = re.search(pattern, lowered)
            if m:
                # Voice-identified speaker is the most reliable name source
                if speaker:
                    return speaker
                # Try to extract name from the match groups
                for group in m.groups():
                    if group and group not in {
                        "device", "assistant", "you", "this", "me", "the"
                    }:
                        return group.capitalize()
                return "Owner"
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _tool_loop(self, messages: list, tools: list, max_rounds: int) -> str:
        """
        Run a tool-calling loop with the LLM.

        Returns the final text response after all tool calls are resolved.
        """
        llm = self._orchestrator.get(ModelRole.LLM)
        for _ in range(max_rounds):
            if tools:
                text, calls = llm.chat_with_tools(messages, tools)
            else:
                text = llm.chat(messages)
                calls = []
            if not calls:
                return text or ""
            messages.append({"role": "assistant", "content": text or "", "tool_calls": calls})
            for call in calls:
                fn_name = call.get("function", {}).get("name", "")
                fn_args = call.get("function", {}).get("arguments", {})
                result = self._dispatch_internal_tool(fn_name, fn_args)
                messages.append({
                    "role": "tool",
                    "name": fn_name,
                    "content": result,
                })
        return ""

    def _dispatch_internal_tool(self, name: str, args: dict) -> str:
        for sub in [self._soul_sub, self._memory_sub]:
            if sub is not None and sub.name == name:
                try:
                    return sub.execute(**args)
                except Exception as exc:
                    return f"Tool error: {exc}"
        return f"Unknown tool: {name}"

    def _owner_is_present(self) -> bool:
        if self._listener is not None and self._listener.owner_present():
            return True
        if self._owner is not None:
            return self._owner.is_owner_present(within_sec=60)
        return False

    def _play_audio_clip(self, audio: np.ndarray) -> None:
        try:
            import sounddevice as sd
            sd.play(audio, 16_000)
            sd.wait()
        except Exception as exc:
            logger.warning("AllyAgent: could not play audio clip: %s", exc)

    def _load_clip_audio(self, path: str) -> Optional[np.ndarray]:
        try:
            with wave.open(path, "rb") as wf:
                raw = wf.readframes(wf.getnframes())
            pcm = np.frombuffer(raw, dtype=np.int16)
            return pcm.astype(np.float32) / 32768.0
        except Exception as exc:
            logger.warning("AllyAgent: could not load clip %s: %s", path, exc)
            return None

    @staticmethod
    def _extract_name_from_reply(text: str) -> Optional[str]:
        """
        Look for a person's name in the user's reply.

        Checks common phrasings like "it's Alice", "that's Bob", "name is Carol",
        then falls back to the first capitalized standalone word.
        """
        patterns = [
            r"\bit['\u2019]?s\s+([A-Z][a-z]+)\b",
            r"\bthat['\u2019]?s\s+([A-Z][a-z]+)\b",
            r"\bname is\s+([A-Z][a-z]+)\b",
            r"\bthis is\s+([A-Z][a-z]+)\b",
            r"\bcall (?:them|him|her)\s+([A-Z][a-z]+)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1)
        # Fallback: first capitalized word that isn't a sentence starter
        words = text.split()
        for i, w in enumerate(words):
            clean = re.sub(r"[^A-Za-z]", "", w)
            if i > 0 and clean and clean[0].isupper() and len(clean) > 1:
                return clean
        return None

    def _fallback_response(self) -> str:
        if not self._is_owner_established:
            return (
                "Hello, I'm Ami. I'm looking for my owner. "
                "Are you the person this device belongs to?"
            )
        return "I'm here whenever you need me."
