"""
KidsStoryAgent — interactive bedtime storytelling for children.

Generates age-appropriate stories on demand with an interactive "what happens
next?" continuation loop. Each session maintains a short story context so the
narrative flows naturally across multiple turns.

Designed for child speakers (detected via voice profile role="child"|"teen")
but usable by anyone. Content is kept family-safe by the system prompt.

Example interactions:
    "Tell me a story about a dragon who is afraid of fire"
    "What happens next?"
    "Give the dragon a best friend who is a tiny mouse"
    "Make it a happy ending"
"""

import logging
from typing import Optional

from agents.base_agent import BaseAgent
from core.model_registry import ModelRole

logger = logging.getLogger(__name__)

# Maximum story segments to keep in context to bound token usage
_MAX_STORY_SEGMENTS = 8

_SYSTEM_PROMPT = """\
You are a warm, imaginative bedtime storyteller for a family AI assistant.
{speaker_line}
Rules:
- Keep all content family-friendly, age-appropriate, and free of violence or scary themes.
- Write in a gentle, engaging oral storytelling style — short sentences, vivid imagery.
- Each response should be 3–5 sentences: one story segment.
- If the child says "what happens next" or similar, continue the story naturally.
- If they suggest a plot twist or new character, weave it into the story creatively.
- End segments with a gentle hook to encourage "what happens next?" naturally.
- When the child asks for an ending, wrap up warmly and wish them goodnight.
"""


class KidsStoryAgent(BaseAgent):
    """
    Interactive bedtime story generator for children.

    Maintains a rolling in-memory story context so each turn builds on the
    previous one. The context resets when the user starts a new story.
    """

    def __init__(self, orchestrator, tool_registry, paths=None):
        super().__init__(orchestrator, tool_registry, paths)
        self._story_messages: list[dict] = []

    def process(self, text: str, speaker: Optional[str] = None, context=None) -> str:
        llm = self._orchestrator.get(ModelRole.LLM)

        # Detect intent to start a fresh story
        lowered = text.lower()
        is_new_story = any(
            phrase in lowered
            for phrase in ("tell me a story", "once upon a time", "start a story", "new story")
        )
        if is_new_story:
            self._story_messages = []
            logger.debug("KidsStoryAgent: starting new story for '%s'", speaker or "unknown")

        name_part = speaker or "the child"
        speaker_line = f"The child's name is {name_part}. Address them by name occasionally." if speaker else ""

        if not self._story_messages:
            # First turn — build story context from scratch
            self._story_messages = [{"role": "system", "content": _SYSTEM_PROMPT.format(speaker_line=speaker_line)}]

        self._story_messages.append({"role": "user", "content": text})

        response = llm.chat(self._story_messages)
        if not response:
            response = "Once upon a time, in a land far away, a great adventure was about to begin…"

        self._story_messages.append({"role": "assistant", "content": response})

        # Trim story context to avoid unbounded growth
        system_msg = self._story_messages[:1]
        recent = self._story_messages[1:]
        if len(recent) > _MAX_STORY_SEGMENTS * 2:
            recent = recent[-(  _MAX_STORY_SEGMENTS * 2):]
        self._story_messages = system_msg + recent

        return response
