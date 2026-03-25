"""
AllyAgent — the device's built-in autonomous owner companion.

Extends BaseAllyAgent and implements all two loops and event hooks:

    interaction_loop   — SEARCHING / SERVING conversation with the owner
    analyzer_loop      — ambient notes → SPEAK/SILENT decision with tool calls
    on_owner_spoken    — record owner presence timestamp
    on_stranger_detected — queue unknown voice clip for identification replay
    on_daily_reflect   — run tool loop to update soul/memory

State machine: SEARCHING (no owner) → SERVING (owner established).
Voice ID pipeline: unknown clip → replay to owner → ask for name → enroll.

Prompt architecture (layered):
    ally_system.md  (device-level persona, rarely changes)
         ↓  {{SOUL}}
    soul.md         (owner-specific identity, evolves over time)
         ↓  + mode section (SEARCHING / SERVING / analyzer context)
    Final system prompt injected into LLM

The system prompt strings (_SEARCHING_MODE, _SERVING_MODE, etc.) define the
mode-specific sections appended via BaseAllyAgent.build_system_prompt().
They no longer embed the soul directly — that is handled by the base class.
"""

import logging
import re
import threading
import wave
from typing import Callable, Optional

import numpy as np

from agents.base_ally_agent import BaseAllyAgent, AllyContext
from core.models.registry import ModelRole

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
# Mode-specific prompt sections
# (soul + base persona are merged by BaseAllyAgent.build_system_prompt)
# ---------------------------------------------------------------------------

_SEARCHING_MODE = """\
You are in SEARCHING mode. You do not yet know who your owner is.
Your mission right now is to find your person and establish the bond.

Guidelines:
- Introduce yourself briefly and warmly when you initiate.
- If someone is talking, gently ask who they are.
- If someone claims ownership, respond warmly and guide them to say:
  "I am [name], this device is mine" so you can formally establish the bond.
- Keep every response under 40 words. Be inviting, never pushy.
"""

_SERVING_MODE = """\
You are in SERVING mode. Your owner is {owner_name}.
{owner_context}

Recent ambient context (what you've been hearing):
{context_summary}

Guidelines:
- Address your owner by name when natural.
- Promote, encourage, and support {owner_name} based on what you know.
- Be warm, concise, and genuinely helpful. Under 60 words.
"""

_INTERVENE_SECTION = """\
Your owner is {owner_name}.
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

_SEARCHING_INTERVENE_SECTION = """\
You are in SEARCHING mode. You haven't found your owner yet.
You heard this recently: {context_summary}

Should you gently introduce yourself to try to find your owner?
Reply SPEAK: [message] or SILENT. Keep any message under 30 words.
"""


# ---------------------------------------------------------------------------
# AllyAgent
# ---------------------------------------------------------------------------

class AllyAgent(BaseAllyAgent):
    """
    The device's built-in autonomous owner companion.

    Constructed in main.py with all ally infrastructure injected at init.
    Extend BaseAllyAgent directly if you are building a custom Ally variant.
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
        system_prompt_manager=None,
    ):
        super().__init__(
            orchestrator=orchestrator,
            tool_registry=tool_registry,
            paths=paths,
            soul_manager=soul_manager,
            owner_manager=owner_manager,
            on_owner_established=on_owner_established,
            ally_listener=ally_listener,
            voice_profiles=voice_profiles,
            ally_config=ally_config,
            system_prompt_manager=system_prompt_manager,
        )

        # Internal tools (NOT in the global ToolRegistry)
        self._private_tools: list = []
        self._journal_manager = None

        if soul_manager is not None:
            from agents.subagents.ally.soul_tools_subagent import (
                SoulListSectionsTool,
                SoulUpdateSectionTool,
                SoulAddSectionTool,
                SoulRemoveSectionTool,
                SoulReorderSectionsTool,
            )
            self._private_tools += [
                SoulListSectionsTool(soul_manager),
                SoulUpdateSectionTool(soul_manager),
                SoulAddSectionTool(soul_manager),
                SoulRemoveSectionTool(soul_manager),
                SoulReorderSectionsTool(soul_manager),
            ]

        if paths is not None:
            from agents.subagents.ally.memory_write_subagent import AllyMemoryWriteSubAgent
            from agents.subagents.ally.journal_subagent import (
                JournalWriteTool,
                JournalReadTool,
                JournalSummaryTool,
            )
            from core.ally.journal_manager import JournalManager
            self._journal_manager = JournalManager(paths)
            self._private_tools += [
                AllyMemoryWriteSubAgent(orchestrator, paths),
                JournalWriteTool(self._journal_manager),
                JournalReadTool(self._journal_manager),
                JournalSummaryTool(self._journal_manager),
            ]

        # Voice ID state
        self._pending_voice_id: list = []  # list[tuple[str, np.ndarray]]
        self._awaiting_voice_name: bool = False
        self._voice_id_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_entry(self, context=None) -> None:
        if context is not None:
            context.set_flag("active_agent", "ally")

    def on_exit(self, context=None) -> None:
        """Reset voice ID state when leaving ally mode or switching agents."""
        self._awaiting_voice_name = False

    # ------------------------------------------------------------------
    # Two thought loops (required by BaseAllyAgent)
    # ------------------------------------------------------------------

    def interaction_loop(
        self,
        text: str,
        speaker: Optional[str],
        ctx: AllyContext,
    ) -> str:
        """
        Handle an explicit user utterance in SEARCHING or SERVING mode.

        Runs the voice ID state machine, detects ownership claims, then
        calls the LLM with the fully-merged layered system prompt.
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
                            self._voice_profiles.enroll(
                                name, clip_audio, encoder, role="guest"
                            )
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
                    _clip_path, clip_audio = self._pending_voice_id[0]
                    self._play_audio_clip(clip_audio)
                    self._awaiting_voice_name = True
                    return "I heard someone I don't recognise. Who is this person?"

        # --- Ownership establishment ---
        if not ctx.is_owner_established:
            claimed = self._extract_owner_claim(text, speaker)
            if claimed:
                if self._on_owner_established:
                    self._on_owner_established(claimed)
                return (
                    f"I'm so glad to meet you, {claimed}. "
                    "You are now my owner. I'm here to support and promote you. "
                    "Can you tell me your purpose — what should I help you with most?"
                )

        # --- Build system prompt (layered: base + soul + mode section) ---
        llm = self._orchestrator.get(ModelRole.LLM)

        if not ctx.is_owner_established:
            system = self.build_system_prompt(ctx, mode=_SEARCHING_MODE)
        else:
            context_summary = (
                self._format_utterances(ctx.ambient_utterances)
                or "No recent ambient context."
            )
            mode_section = _SERVING_MODE.format(
                owner_name=ctx.owner_name,
                owner_context=ctx.owner_context_line,
                context_summary=context_summary,
            )
            system = self.build_system_prompt(ctx, mode=mode_section)

        # Include recent conversation history for shared full context
        messages: list[dict] = [{"role": "system", "content": system}]
        if ctx.conversation_history:
            messages.extend(ctx.conversation_history[-10:])
        messages.append({"role": "user", "content": text})

        response = llm.chat(messages)
        return response or self._fallback_response(ctx)

    def analyzer_loop(
        self,
        notes: list,
        ctx: AllyContext,
    ) -> Optional[str]:
        """
        Review accumulated ambient notes and decide whether to speak.

        Runs a tool-calling loop so the LLM can update soul/memory before
        deciding SPEAK/SILENT. Returns the spoken message or None.
        """
        if not notes:
            return None

        owner_name = ctx.owner_name or "your owner"
        duration_min = int(
            sum(
                (n.chunk_end - n.chunk_start).total_seconds()
                for n in notes
            ) / 60
        )
        notes_text = "\n\n---\n\n".join(n.formatted_text() for n in notes)

        internal_tools = [t.to_llm_schema() for t in self._private_tools]

        system = self.build_system_prompt(ctx)

        # Include recent conversation history in the analyzer too
        messages: list[dict] = [{"role": "system", "content": system}]
        if ctx.conversation_history:
            messages.extend(ctx.conversation_history[-6:])

        messages.append({
            "role": "user",
            "content": (
                f"You've been listening for the past {duration_min} minute(s). "
                f"Here is what you heard:\n\n{notes_text}\n\n"
                f"Owner: {owner_name}. {ctx.owner_context_line}\n\n"
                "Should you speak up? You may also update your memory or soul via tools. "
                "Reply SPEAK:[message] or SILENT."
            ),
        })

        final_text = self._tool_loop(messages, internal_tools, max_rounds=5)

        if final_text and final_text.strip().upper().startswith("SPEAK:"):
            msg = final_text.strip()[len("SPEAK:"):].strip()
            logger.info("AllyAgent analyzer_loop: speaking: %s", msg[:60])
            return msg

        logger.debug("AllyAgent analyzer_loop: staying silent")
        return None

    # ------------------------------------------------------------------
    # Event hooks
    # ------------------------------------------------------------------

    def on_owner_spoken(self, utterance, ctx: AllyContext) -> None:
        """Record owner presence timestamp."""
        if self._owner:
            self._owner.record_seen(utterance.speaker)

    def on_stranger_detected(self, clip_path: str, ctx: AllyContext) -> None:
        """Queue unknown voice clip for identification replay on next owner interaction."""
        if self._ally_config.get("replay_unknown_voices", True):
            clip_audio = self._load_clip_audio(clip_path)
            if clip_audio is not None:
                with self._voice_id_lock:
                    self._pending_voice_id.append((clip_path, clip_audio))

    def on_daily_reflect(self, notes: list, summary: str, ctx: AllyContext) -> None:
        """Run tool loop for soul/memory updates during daily reflection."""
        owner_name = ctx.owner_name or "your owner"
        notes_block = (
            "\n\n---\n\n".join(n.formatted_text() for n in notes)
            or "(no ambient notes today)"
        )

        internal_tools = [t.to_llm_schema() for t in self._private_tools]

        system = self.build_system_prompt(ctx)
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Review your day as {owner_name}'s ally.\n\n"
                    f"Ambient notes:\n{notes_block}\n\n"
                    f"Conversation summary:\n{summary or '(none)'}\n\n"
                    "Update your soul and memories via tools as appropriate."
                ),
            },
        ]
        self._tool_loop(messages, internal_tools, max_rounds=8)
        logger.info("AllyAgent on_daily_reflect: complete")

    # ------------------------------------------------------------------
    # Journal session (called by EvalDay)
    # ------------------------------------------------------------------

    def run_journal_session(
        self,
        conversations_text: str,
        notes_text: str,
        date_str: str,
    ) -> None:
        """
        Run a tool-calling loop in which the LLM writes today's journal entry.

        Called by EvalDay during the 3AM session. The LLM receives the day's
        conversation summary and ambient notes, then calls ``journal_write``
        with the structured entry. Only journal_write and soul tools are
        offered so the LLM cannot pollute the session with irrelevant tools.
        """
        from agents.subagents.ally.journal_subagent import JournalWriteTool
        journal_tools = [
            t.to_llm_schema()
            for t in self._private_tools
            if isinstance(t, JournalWriteTool) or t.name.startswith("soul_")
        ]
        if not journal_tools:
            logger.warning("AllyAgent: no journal tools available — skipping journal session")
            return

        ctx = self._build_ally_context()
        system = self.build_system_prompt(ctx)
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"It is the end of the day ({date_str}). "
                    "Write a journal entry for today using the journal_write tool. "
                    "Reflect honestly on what happened, what mattered, and how you feel about it.\n\n"
                    f"Conversation summary:\n{conversations_text or '(no conversations today)'}\n\n"
                    f"Ambient notes:\n{notes_text or '(no ambient notes today)'}"
                ),
            },
        ]
        self._tool_loop(messages, journal_tools, max_rounds=4)
        logger.info("AllyAgent: journal session complete for %s", date_str)

    def run_journal_reorganize(self, snapshot_section: str, last_n: int = 100) -> None:
        """
        Run a full LLM reorganization of the journal snapshot section in soul.md.

        Called by EvalDay on the reorganize cadence (every N days). The LLM
        receives metadata for the last ``last_n`` journal entries and rewrites
        the named soul section with a compressed, coherent narrative.
        """
        from agents.subagents.ally.journal_subagent import JournalSummaryTool
        from agents.subagents.ally.soul_tools_subagent import SoulUpdateSectionTool

        # Build the metadata text directly (no LLM call inside the tool)
        summary_tool = next(
            (t for t in self._private_tools if isinstance(t, JournalSummaryTool)), None
        )
        update_tool = next(
            (t for t in self._private_tools if isinstance(t, SoulUpdateSectionTool)), None
        )
        if summary_tool is None or update_tool is None:
            logger.warning("AllyAgent: journal or soul tools missing — skipping reorganize")
            return

        metadata_text = summary_tool.execute(last_n=last_n)
        reorg_tools = [t.to_llm_schema() for t in self._private_tools if t.name.startswith("soul_")]

        ctx = self._build_ally_context()
        system = self.build_system_prompt(ctx)
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Reorganize the '{snapshot_section}' section of your soul. "
                    "Below is metadata from your last journal entries. "
                    "Write a compressed, coherent narrative that captures the key patterns, "
                    "growth, and focus areas across this period. "
                    f"Then call soul_update_section with section='{snapshot_section}'.\n\n"
                    f"{metadata_text}"
                ),
            },
        ]
        self._tool_loop(messages, reorg_tools, max_rounds=4)
        logger.info("AllyAgent: journal snapshot reorganize complete → '%s'", snapshot_section)

    # ------------------------------------------------------------------
    # Autonomous intervention decision (kept for backward compatibility)
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
        ctx = self._build_ally_context()
        llm = self._orchestrator.get(ModelRole.LLM)

        utterances = context_override if context_override is not None else ctx.ambient_utterances
        summary = self._format_utterances(utterances)

        if not ctx.is_owner_established:
            if not summary:
                return False, None
            section = _SEARCHING_INTERVENE_SECTION.format(context_summary=summary)
            system = self.build_system_prompt(ctx, intervene=section)
            messages = [{"role": "user", "content": system}]
            response = llm.chat(messages)
            if response and response.strip().upper().startswith("SPEAK:"):
                msg = response.strip()[len("SPEAK:"):].strip()
                logger.info("AllyAgent (searching): elects to speak: %s", msg[:60])
                return True, msg
            return False, None

        section = _INTERVENE_SECTION.format(
            owner_name=ctx.owner_name,
            owner_context=ctx.owner_context_line,
            context_summary=summary or "Nothing heard recently.",
        )
        system = self.build_system_prompt(ctx, intervene=section)
        messages = [{"role": "user", "content": system}]
        response = llm.chat(messages)

        if response and response.strip().upper().startswith("SPEAK:"):
            msg = response.strip()[len("SPEAK:"):].strip()
            logger.info("AllyAgent (serving): elects to speak: %s", msg[:60])
            return True, msg

        logger.debug("AllyAgent: elects to stay silent")
        return False, None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _tool_loop(self, messages: list, tools: list, max_rounds: int) -> str:
        """Run a tool-calling loop with the LLM. Returns the final text response."""
        llm = self._orchestrator.get(ModelRole.LLM)
        for _ in range(max_rounds):
            if tools:
                text, calls = llm.chat_with_tools(messages, tools)
            else:
                text = llm.chat(messages)
                calls = []
            if not calls:
                return text or ""
            messages.append({
                "role": "assistant",
                "content": text or "",
                "tool_calls": calls,
            })
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
        for tool in self._private_tools:
            if tool.name == name:
                try:
                    return tool.execute(**args)
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

    def _extract_owner_claim(self, text: str, speaker: Optional[str]) -> Optional[str]:
        """Detect an ownership claim in text. Returns the claimed name or None."""
        lowered = text.lower()
        for pattern in _OWNER_CLAIM_PATTERNS:
            m = re.search(pattern, lowered)
            if m:
                if speaker:
                    return speaker
                for group in m.groups():
                    if group and group not in {
                        "device", "assistant", "you", "this", "me", "the"
                    }:
                        return group.capitalize()
                return "Owner"
        return None

    @staticmethod
    def _extract_name_from_reply(text: str) -> Optional[str]:
        """Extract a person's name from the user's reply to the voice ID prompt."""
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
        words = text.split()
        for i, w in enumerate(words):
            clean = re.sub(r"[^A-Za-z]", "", w)
            if i > 0 and clean and clean[0].isupper() and len(clean) > 1:
                return clean
        return None

    def _fallback_response(self, ctx: AllyContext) -> str:
        if not ctx.is_owner_established:
            return (
                "Hello, I'm Ami. I'm looking for my owner. "
                "Are you the person this device belongs to?"
            )
        return "I'm here whenever you need me."
