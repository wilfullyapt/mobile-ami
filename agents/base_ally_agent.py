"""
BaseAllyAgent — abstract base for all Ally-mode agent variants.

Provides the two-loop architecture, named event hooks, and layered system
prompt assembly that make Ally mode composable for add-on developers.

Architecture overview
---------------------

Two thought loops
~~~~~~~~~~~~~~~~~
    interaction_loop(text, speaker, ctx) → str
        Called on every explicit user utterance. Receives the full shared
        AllyContext (conversation history, ambient notes, soul, owner state).

    analyzer_loop(notes, ctx) → Optional[str]
        Called every check_interval_sec with accumulated AmbientNotes.
        Decides autonomously whether to speak. Return a message or None.

Both loops receive the same AllyContext so neither operates with an
incomplete picture of what has happened.

Named event hooks (override any/all — all default to no-ops)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    on_owner_spoken(utterance, ctx)
        The owner's voice was detected in the ambient stream.

    on_owner_absent(seconds_absent, ctx) → Optional[str]
        Owner not heard for owner_absent_threshold_sec. Return a message or None.

    on_stranger_detected(clip_path, ctx)
        An unrecognised voice clip is available for identification.

    on_ambient_context(notes, ctx) → Optional[str]
        Pre-check before analyzer_loop. Return a message to skip the full
        analyzer evaluation, or None to proceed normally.

    on_daily_reflect(notes, summary, ctx)
        Once-per-day reflection. Load notes, update soul/memory, log insights.

System prompt assembly (layered)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    build_system_prompt(ctx, **extra_sections)
        Merges ally_system.md (device-level persona base layer) with soul.md
        (owner-specific identity overlay) via a {{SOUL}} marker in the template.
        Extra named sections are appended after the merge — use them to inject
        mode-specific guidance (SEARCHING vs SERVING, analyzer context, etc.).

Composability for add-on developers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
To build a custom Ally variant:

    1. Extend BaseAllyAgent.
    2. Implement interaction_loop() and analyzer_loop().
    3. Override whichever on_* hooks you need.
    4. Optionally ship your own ally_system.md.default alongside your agent
       and pass SystemPromptManager(paths, project_root=your_pkg_root) to
       the system_prompt_manager parameter.

The manifest.json multi-agent add-on contract works unchanged.
AllyAgent in agents/ally_agent.py is the reference built-in implementation.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional, TYPE_CHECKING

from agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from core.models.orchestrator import ModelOrchestrator
    from agents.tools.tool_registry import ToolRegistry
    from core.ami_paths import AmiPaths
    from core.ally.soul import SoulManager
    from core.ally.listener import AllyListener, AmbientUtterance
    from core.ally.system_prompt_manager import SystemPromptManager
    from core.owner_manager import OwnerManager
    from core.agent_context import AgentContext
    from core.ally.ambient_note import AmbientNote

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared context dataclass
# ---------------------------------------------------------------------------

@dataclass
class AllyContext:
    """
    Full shared context delivered to every ally hook and thought loop.

    Both the interaction loop and the interval analyzer receive the same
    AllyContext so neither operates with an incomplete picture.

    Fields
    ------
    soul_text:
        Raw content of soul.md (the owner-specific identity overlay).
    system_base:
        Raw content of ally_system.md (the device-level persona base layer).
    owner_name:
        Display name of the device owner, or None in SEARCHING mode.
    owner_context_line:
        Human-readable sentence about when the owner was last heard.
    is_owner_established:
        True = SERVING mode (owner known). False = SEARCHING mode.
    conversation_history:
        Recent {role, content} message dicts from the pipeline AgentContext.
    ambient_notes:
        AmbientNote objects accumulated since the last check cycle.
    ambient_utterances:
        Recent AmbientUtterance objects from the rolling listener buffer.
    agent_context:
        The pipeline's shared AgentContext (may be None in tests).
    """

    soul_text: str
    system_base: str
    owner_name: Optional[str]
    owner_context_line: str
    is_owner_established: bool
    conversation_history: list[dict] = field(default_factory=list)
    ambient_notes: list = field(default_factory=list)
    ambient_utterances: list = field(default_factory=list)
    agent_context: Optional["AgentContext"] = None
    soul_framework: list[str] = field(default_factory=list)
    """
    Ordered list of section headings the user wants the soul to contain.
    Read from config.ally.soul_sections. Injected into the system prompt as a
    framework hint — the Ally may follow, adapt, or ignore it.
    """


# ---------------------------------------------------------------------------
# BaseAllyAgent
# ---------------------------------------------------------------------------

class BaseAllyAgent(BaseAgent):
    """
    Abstract base for all Ally-mode agents.

    At minimum, implement ``interaction_loop`` and ``analyzer_loop``.
    Override any ``on_*`` hooks you want to react to.

    The constructor signature is a superset of BaseAgent's. All parameters
    are optional beyond orchestrator and tool_registry so that concrete
    subclasses can be instantiated with only the infrastructure they need.
    Unknown keyword arguments are silently ignored so future infrastructure
    additions don't break existing subclasses.
    """

    def __init__(
        self,
        orchestrator: "ModelOrchestrator",
        tool_registry: "ToolRegistry",
        paths: "Optional[AmiPaths]" = None,
        soul_manager: "Optional[SoulManager]" = None,
        owner_manager: "Optional[OwnerManager]" = None,
        on_owner_established: Optional[Callable[[str], None]] = None,
        ally_listener: "Optional[AllyListener]" = None,
        voice_profiles=None,
        ally_config: Optional[dict] = None,
        system_prompt_manager: "Optional[SystemPromptManager]" = None,
        **_extra,  # absorb unknown kwargs for forward compatibility
    ):
        super().__init__(orchestrator, tool_registry, paths)
        self._soul = soul_manager
        self._owner = owner_manager
        self._on_owner_established = on_owner_established
        self._listener = ally_listener
        self._voice_profiles = voice_profiles
        self._ally_config = ally_config or {}
        self._system_prompt_mgr = system_prompt_manager

    # ------------------------------------------------------------------
    # Abstract: thought loops — implement both in your subclass
    # ------------------------------------------------------------------

    @abstractmethod
    def interaction_loop(
        self,
        text: str,
        speaker: Optional[str],
        ctx: AllyContext,
    ) -> str:
        """
        Handle an explicit user utterance. Return a spoken response string.

        The full shared context (conversation history, ambient notes, soul,
        owner state) is pre-assembled in ``ctx`` before this is called.
        """

    @abstractmethod
    def analyzer_loop(
        self,
        notes: list,
        ctx: AllyContext,
    ) -> Optional[str]:
        """
        Autonomously decide whether to speak based on ambient context.

        Called every check_interval_sec with the latest AmbientNote objects.
        Return a spoken message string to intervene, or None to stay silent.
        """

    # ------------------------------------------------------------------
    # Event hooks — override any/all (default: no-ops)
    # ------------------------------------------------------------------

    def on_owner_spoken(
        self,
        utterance: "AmbientUtterance",
        ctx: AllyContext,
    ) -> None:
        """Called each time the owner's voice is identified in the ambient stream."""

    def on_owner_absent(
        self,
        seconds_absent: float,
        ctx: AllyContext,
    ) -> Optional[str]:
        """
        Called when the owner has not been heard for owner_absent_threshold_sec.

        Return a spoken message string to check in proactively, or None to
        stay silent. Default: always silent.
        """
        return None

    def on_stranger_detected(
        self,
        clip_path: str,
        ctx: AllyContext,
    ) -> None:
        """Called when an unrecognised voice clip is available for identification."""

    def on_ambient_context(
        self,
        notes: list,
        ctx: AllyContext,
    ) -> Optional[str]:
        """
        Pre-check hook called before analyzer_loop.

        Return a spoken message to intervene immediately (skipping the full
        analyzer_loop evaluation), or None to proceed normally.
        Useful for lightweight pattern checks that don't need a full LLM call.
        """
        return None

    def on_daily_reflect(
        self,
        notes: list,
        summary: str,
        ctx: AllyContext,
    ) -> None:
        """
        Once-per-day reflection hook.

        Called with today's AmbientNote objects and the LLM conversation
        summary. Use this to update soul/memory, generate self-reflection,
        or log insights from the day.
        """

    # ------------------------------------------------------------------
    # System prompt assembly (layered: base + soul overlay)
    # ------------------------------------------------------------------

    def build_system_prompt(self, ctx: AllyContext, **extra_sections: str) -> str:
        """
        Merge the ally_system.md base layer with the soul.md overlay.

        The base template uses ``{{SOUL}}`` as the injection marker.
        If the marker is absent, the soul text is appended after the base.

        ``extra_sections`` are appended as named text blocks after the merge,
        separated by ``---`` dividers. Use them to inject mode-specific
        guidance (SEARCHING vs SERVING state, analyzer framing, etc.).

        Example::

            system = self.build_system_prompt(
                ctx,
                mode=_SERVING_SECTION.format(owner_name=ctx.owner_name, ...),
            )
        """
        base = ctx.system_base
        soul = ctx.soul_text

        if base:
            if "{{SOUL}}" in base:
                merged = base.replace("{{SOUL}}", soul)
            else:
                # No marker: append soul after base
                merged = (base + "\n\n" + soul) if soul else base
        else:
            # No base template: use soul alone
            merged = soul

        # Inject the user's soul framework preference as a hint (never enforced)
        if ctx.soul_framework:
            framework_lines = "\n".join(f"- {h}" for h in ctx.soul_framework)
            framework_hint = (
                "## Soul Framework (user preference)\n"
                "The user has indicated they'd like the soul organised around these sections:\n"
                f"{framework_lines}\n"
                "You may follow, adapt, or ignore this as you see fit."
            )
            merged = merged + "\n\n---\n\n" + framework_hint

        if extra_sections:
            merged = merged + "\n\n---\n\n" + "\n\n---\n\n".join(extra_sections.values())

        return merged

    # ------------------------------------------------------------------
    # BaseAgent interface wiring
    # ------------------------------------------------------------------

    def process(
        self,
        text: str,
        speaker: Optional[str] = None,
        context: "Optional[AgentContext]" = None,
    ) -> str:
        """
        Orchestrates a direct user interaction:
          1. Build shared AllyContext.
          2. Fire on_owner_spoken if the owner is speaking.
          3. Delegate to interaction_loop.
        """
        ctx = self._build_ally_context(context=context)

        if speaker and ctx.owner_name and speaker == ctx.owner_name:
            try:
                from core.ally.listener import AmbientUtterance
                from datetime import datetime, timezone
                utt = AmbientUtterance(
                    speaker=speaker,
                    is_owner=True,
                    text=text,
                    timestamp=datetime.now(timezone.utc),
                )
                self.on_owner_spoken(utt, ctx)
            except Exception as exc:
                logger.debug("on_owner_spoken hook error: %s", exc)

        return self.interaction_loop(text, speaker, ctx)

    def interval_listen(
        self,
        notes: list,
        context: "Optional[AgentContext]" = None,
    ) -> Optional[str]:
        """
        Orchestrates autonomous ambient evaluation:
          1. Build shared AllyContext with accumulated notes.
          2. Fire on_ambient_context pre-check (may short-circuit).
          3. Delegate to analyzer_loop.
          4. Fire on_stranger_detected for any unrecognised voice clips.
          5. Fire on_owner_absent if the owner absence threshold is crossed.
        """
        ctx = self._build_ally_context(notes=notes, context=context)

        # Pre-check — lightweight hook that can short-circuit the full LLM call
        pre = self.on_ambient_context(notes, ctx)
        if pre is not None:
            return pre

        result = self.analyzer_loop(notes, ctx)

        # Notify about unknown voice clips
        unknown_clips = [
            clip
            for note in notes
            for clip in getattr(note, "unknown_clip_paths", [])
        ]
        for clip_path in unknown_clips:
            try:
                self.on_stranger_detected(clip_path, ctx)
            except Exception as exc:
                logger.debug("on_stranger_detected hook error: %s", exc)

        # Owner absence check — only fires if analyzer_loop stayed silent
        if result is None and self._owner is not None:
            absent_threshold = self._ally_config.get("owner_absent_threshold_sec", 300)
            secs = self._owner.seconds_since_owner_seen()
            if secs is not None and secs >= absent_threshold:
                absent_msg = self.on_owner_absent(secs, ctx)
                if absent_msg:
                    return absent_msg

        return result

    def daily_update(
        self,
        context: "Optional[AgentContext]" = None,
    ) -> None:
        """
        Orchestrates the once-per-day reflection cycle:
          1. Load today's AmbientNote files from disk.
          2. Load the day's conversation summary from memory.
          3. Build shared AllyContext.
          4. Delegate to on_daily_reflect.
        """
        from datetime import date
        import json

        today_str = date.today().isoformat()
        today_prefix = today_str.replace("-", "")

        notes: list = []
        if self._paths is not None:
            notes_dir = self._paths.ally_notes_dir
            if notes_dir.exists():
                for note_file in sorted(notes_dir.glob(f"{today_prefix}*.json")):
                    try:
                        from core.ally.ambient_note import AmbientNote
                        note = AmbientNote.from_json(note_file.read_text())
                        notes.append(note)
                    except Exception as exc:
                        logger.warning(
                            "daily_update: could not load note %s: %s", note_file, exc
                        )

        summary = ""
        if self._paths is not None:
            mem_file = self._paths.memory_dir / f"{today_str}.json"
            if mem_file.exists():
                try:
                    data = json.loads(mem_file.read_text())
                    summary = data.get("summary", "")
                except Exception:
                    pass

        ctx = self._build_ally_context(notes=notes, context=context)
        self.on_daily_reflect(notes, summary, ctx)
        logger.info("BaseAllyAgent: daily_update complete for %s", today_str)

    @classmethod
    def supports_ally_mode(cls) -> bool:
        """Always True for BaseAllyAgent subclasses."""
        return True

    # ------------------------------------------------------------------
    # AllyContext assembly (called before every hook/loop invocation)
    # ------------------------------------------------------------------

    def _build_ally_context(
        self,
        notes: Optional[list] = None,
        context: "Optional[AgentContext]" = None,
    ) -> AllyContext:
        """Assemble the full shared AllyContext from current runtime state."""
        soul_text = (
            self._soul.read(has_owner=self._is_owner_established)
            if self._soul else ""
        )
        system_base = self._system_prompt_mgr.read() if self._system_prompt_mgr else ""

        owner_name = self._owner.owner_name if self._owner else None
        is_owner_established = self._is_owner_established
        owner_context_line = self._owner_context_line

        # Conversation history from the pipeline AgentContext
        conversation_history: list[dict] = []
        if context is not None and hasattr(context, "history"):
            conversation_history = list(context.history or [])

        # Ambient utterances from the rolling listener buffer
        ambient_utterances = (
            self._listener.get_recent_context() if self._listener else []
        )

        soul_framework = list(self._ally_config.get("soul_sections", []))

        return AllyContext(
            soul_text=soul_text,
            system_base=system_base,
            owner_name=owner_name,
            owner_context_line=owner_context_line,
            is_owner_established=is_owner_established,
            conversation_history=conversation_history,
            ambient_notes=notes or [],
            ambient_utterances=ambient_utterances,
            agent_context=context,
            soul_framework=soul_framework,
        )

    # ------------------------------------------------------------------
    # Shared helper properties (available to subclasses)
    # ------------------------------------------------------------------

    @property
    def _is_owner_established(self) -> bool:
        return self._owner is not None and self._owner.has_owner

    @property
    def _owner_context_line(self) -> str:
        if not self._owner:
            return ""
        secs = self._owner.seconds_since_owner_seen()
        owner_name = self._owner.owner_name or "your owner"
        if secs is None:
            return f"You have not yet heard {owner_name} speak since startup."
        if secs < 60:
            return f"{owner_name} spoke less than a minute ago."
        if secs < 3600:
            return f"{owner_name} was last heard {int(secs / 60)} minute(s) ago."
        return f"{owner_name} was last heard {int(secs / 3600)} hour(s) ago."

    def _format_utterances(self, utterances: list, max_count: int = 12) -> str:
        """Format a list of AmbientUtterance objects as a readable transcript."""
        if not utterances:
            return ""
        lines = []
        for u in utterances[-max_count:]:
            ago = int(u.seconds_ago())
            who = u.speaker or "unknown"
            owner_tag = " [owner]" if u.is_owner else ""
            lines.append(f"[{ago}s ago, {who}{owner_tag}]: {u.text}")
        return "\n".join(lines)
