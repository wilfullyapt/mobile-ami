import logging
import os
from typing import Optional

import ollama

from core.models.registry import ModelSpec

logger = logging.getLogger(__name__)


class LLM:
    """
    Ollama-backed LLM wrapper.

    Supports plain chat and tool-calling chat. The model name is taken
    from the ModelSpec so it can be changed via the orchestrator without
    modifying code.

    When spec.path is set (resolved to ~/.amini/models/llm/ by AmiPaths),
    OLLAMA_MODELS is pointed there so Ollama stores its blobs in the user's
    home directory rather than the system default.
    """

    def __init__(self, spec: ModelSpec):
        if spec.path:
            os.environ.setdefault("OLLAMA_MODELS", spec.path)
        self._model = spec.name

    def query(self, prompt: str) -> str:
        """Simple single-turn query, returns assistant text."""
        response = ollama.chat(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"]

    def chat(self, messages: list[dict]) -> str:
        """Multi-turn chat with a messages list, returns assistant text."""
        response = ollama.chat(model=self._model, messages=messages)
        return response["message"]["content"]

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> tuple[str, list[dict]]:
        """
        Send a messages list with optional tool schemas to Ollama.

        Returns:
            (text_response, tool_calls)
            tool_calls is a list of dicts: [{"name": str, "args": dict}, ...]
            If the model chose not to call any tools, tool_calls is [].
        """
        kwargs = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools

        response = ollama.chat(**kwargs)
        msg = response["message"]

        text = msg.get("content") or ""
        raw_calls = msg.get("tool_calls") or []

        parsed_calls = []
        for call in raw_calls:
            fn = call.get("function", {})
            parsed_calls.append({
                "name": fn.get("name", ""),
                "args": fn.get("arguments", {}),
            })

        return text, parsed_calls

    # NOTE: For Hailo acceleration, compile llama.cpp with the Hailo backend
    # and point ollama at the resulting binary, or use the official Hailo LLM SDK.
