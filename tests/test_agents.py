"""Unit tests for agents/qa_agent.py and agents/block_timer_agent.py"""

import pytest
from unittest.mock import MagicMock, call, patch

from agents.qa_agent import QAAgent
from agents.block_timer_agent import BlockTimerAgent
from agents.tools.tool_registry import ToolRegistry
from agents.tools.base_tool import BaseTool, ToolParam
from core.models.registry import ModelRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm(responses=None):
    """
    Build a mock LLM.

    responses: list of (text, tool_calls) tuples returned by chat_with_tools
               in order. If exhausted, returns ("fallback", []).
    """
    llm = MagicMock()
    if responses is None:
        responses = [("default response", [])]

    call_iter = iter(responses)

    def chat_with_tools(messages, tools=None):
        try:
            return next(call_iter)
        except StopIteration:
            return ("fallback", [])

    llm.chat_with_tools.side_effect = chat_with_tools
    llm.chat.return_value = "final fallback"
    return llm


def _make_orchestrator(llm=None, tts=None):
    orch = MagicMock()
    _llm = llm or _make_llm()
    _tts = tts or MagicMock()
    orch.get.side_effect = lambda role: {
        ModelRole.LLM: _llm,
        ModelRole.TTS: _tts,
    }[role]
    return orch, _llm, _tts


class CountTool(BaseTool):
    """A test tool that counts calls."""
    name = "count"
    description = "Increment a counter."
    parameters = [ToolParam("amount", "integer", "Amount to add")]

    def __init__(self):
        self.total = 0

    def execute(self, amount: int = 1) -> str:
        self.total += int(amount)
        return f"total={self.total}"


# ---------------------------------------------------------------------------
# QAAgent
# ---------------------------------------------------------------------------

class TestQAAgentNoTools:
    def _make(self, llm=None):
        orch, _llm, tts = _make_orchestrator(llm)
        registry = ToolRegistry()
        agent = QAAgent(orch, registry)
        return agent, _llm

    def test_returns_llm_response_when_no_tool_calls(self):
        agent, llm = self._make(_make_llm([("The answer is 42.", [])]))
        result = agent.process("What is 6 times 7?")
        assert result == "The answer is 42."

    def test_fallback_message_on_empty_response(self):
        agent, llm = self._make(_make_llm([("", [])]))
        result = agent.process("say nothing")
        assert "not sure" in result.lower()

    def test_chat_with_tools_called_with_user_message(self):
        agent, llm = self._make(_make_llm([("ok", [])]))
        agent.process("test input")
        args = llm.chat_with_tools.call_args
        messages = args[0][0]
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "test input"

    def test_no_tools_registered_passes_none(self):
        agent, llm = self._make(_make_llm([("ok", [])]))
        agent.process("hi")
        # tools=None when get_tools() returns []
        args = llm.chat_with_tools.call_args
        tools_arg = args[0][1]
        assert tools_arg is None


class TestQAAgentWithTools:
    def _make_with_tool(self, responses):
        count_tool = CountTool()
        llm = _make_llm(responses)
        orch, _, tts = _make_orchestrator(llm)
        registry = ToolRegistry()
        registry.register(count_tool)

        class QAWithTool(QAAgent):
            def get_tools(self):
                return [count_tool]

        agent = QAWithTool(orch, registry)
        return agent, llm, count_tool

    def test_single_tool_call_then_response(self):
        tool_call = {"name": "count", "args": {"amount": 3}}
        agent, llm, tool = self._make_with_tool([
            ("", [tool_call]),
            ("Counter updated.", []),
        ])
        result = agent.process("add 3")
        assert result == "Counter updated."
        assert tool.total == 3

    def test_multiple_tool_calls_in_one_round(self):
        tool_calls = [
            {"name": "count", "args": {"amount": 1}},
            {"name": "count", "args": {"amount": 2}},
        ]
        agent, llm, tool = self._make_with_tool([
            ("", tool_calls),
            ("Done.", []),
        ])
        result = agent.process("add 1 and 2")
        assert result == "Done."
        assert tool.total == 3

    def test_tool_results_appended_to_messages(self):
        tool_call = {"name": "count", "args": {"amount": 5}}
        agent, llm, tool = self._make_with_tool([
            ("", [tool_call]),
            ("ok", []),
        ])
        agent.process("add 5")
        # Second call should include tool result messages
        second_call_messages = llm.chat_with_tools.call_args_list[1][0][0]
        roles = [m["role"] for m in second_call_messages]
        assert "tool" in roles

    def test_max_tool_rounds_respected(self):
        """If LLM keeps requesting tools, fallback to llm.chat() after max rounds."""
        tool_call = {"name": "count", "args": {"amount": 1}}
        # Always return a tool call (5 rounds = _MAX_TOOL_ROUNDS)
        agent, llm, tool = self._make_with_tool(
            [("", [tool_call])] * 10  # more than _MAX_TOOL_ROUNDS
        )
        result = agent.process("loop forever")
        # After exhausting rounds, falls back to llm.chat()
        llm.chat.assert_called_once()

    def test_schema_passed_to_llm(self):
        count_tool = CountTool()
        llm = _make_llm([("ok", [])])
        orch, _, tts = _make_orchestrator(llm)
        registry = ToolRegistry()
        registry.register(count_tool)

        class QAWithTool(QAAgent):
            def get_tools(self):
                return [count_tool]

        agent = QAWithTool(orch, registry)
        agent.process("test")

        tools_arg = llm.chat_with_tools.call_args[0][1]
        assert tools_arg is not None
        assert len(tools_arg) == 1
        assert tools_arg[0]["function"]["name"] == "count"


# ---------------------------------------------------------------------------
# BlockTimerAgent
# ---------------------------------------------------------------------------

class TestBlockTimerAgent:
    def _make(self, llm_responses, tts=None):
        llm = _make_llm(llm_responses)
        _tts = tts or MagicMock()
        orch, _, _ = _make_orchestrator(llm, _tts)
        registry = ToolRegistry()

        from agents.tools.timer_tool import TimerTool
        timer = TimerTool(on_speak=_tts.speak)
        registry.register(timer)

        agent = BlockTimerAgent(orch, registry)
        return agent, llm, _tts

    def test_tool_call_triggers_timer(self):
        tool_call = {"name": "set_timer", "args": {"minutes": 25, "label": "focus"}}
        agent, llm, tts = self._make([("", [tool_call])])
        with patch("agents.tools.timer_tool.threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            result = agent.process("start a 25 minute focus block")
        assert "25" in result

    def test_no_tool_call_returns_llm_text(self):
        agent, llm, tts = self._make([("No timer set.", [])])
        result = agent.process("how are you?")
        assert result == "No timer set."

    def test_no_tool_call_fallback_message_on_empty_response(self):
        agent, llm, tts = self._make([("", [])])
        result = agent.process("unknown command")
        assert "not recognized" in result.lower()

    def test_get_tools_returns_timer_tool(self):
        llm = _make_llm([("", [])])
        _tts = MagicMock()
        orch, _, _ = _make_orchestrator(llm, _tts)
        registry = ToolRegistry()
        agent = BlockTimerAgent(orch, registry)
        tools = agent.get_tools()
        assert len(tools) == 1
        assert tools[0].name == "set_timer"

    def test_timer_tool_on_speak_uses_tts(self):
        from agents.tools.timer_tool import TimerTool
        _tts = MagicMock()
        tool_call = {"name": "set_timer", "args": {"minutes": 0, "label": "quick"}}
        agent, llm, tts = self._make([("", [tool_call])], _tts)

        # Override get_tools() so the timer uses our _tts mock
        timer = TimerTool(on_speak=_tts.speak)
        agent._orchestrator.get.side_effect = lambda role: {
            ModelRole.LLM: llm,
            ModelRole.TTS: _tts,
        }[role]

        with patch("agents.tools.timer_tool.threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            agent.process("start 0-minute quick timer")
