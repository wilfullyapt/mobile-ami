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
from typing import Callable, Optional

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
    ):
        super().__init__(orchestrator, tool_registry, paths)
        self._soul = soul_manager
        self._owner = owner_manager
        self._on_owner_established = on_owner_established
        self._listener = ally_listener  # Optional[AllyListener]

    # ------------------------------------------------------------------
    # Standard agent interaction (called by pipeline)
    # ------------------------------------------------------------------

    def process(self, text: str, speaker: Optional[str] = None, context=None) -> str:
        """
        Handle an explicit user interaction.

        If the device has no owner, checks whether the user is claiming
        ownership and fires on_owner_established if so.
        """
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

    def _fallback_response(self) -> str:
        if not self._is_owner_established:
            return (
                "Hello, I'm Ami. I'm looking for my owner. "
                "Are you the person this device belongs to?"
            )
        return "I'm here whenever you need me."
