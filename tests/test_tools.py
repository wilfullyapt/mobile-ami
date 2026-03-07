"""Unit tests for agents/tools/"""

import pytest
import threading
from unittest.mock import MagicMock, patch

from agents.tools.base_tool import BaseTool, ToolParam
from agents.tools.tool_registry import ToolRegistry
from agents.tools.timer_tool import TimerTool


# ---------------------------------------------------------------------------
# Concrete BaseTool subclass for testing
# ---------------------------------------------------------------------------

class EchoTool(BaseTool):
    name = "echo"
    description = "Echo back the input text."
    parameters = [
        ToolParam("text", "string", "Text to echo back", required=True),
        ToolParam("prefix", "string", "Optional prefix", required=False),
    ]

    def execute(self, text: str, prefix: str = "") -> str:
        return f"{prefix}{text}"


class NoParamTool(BaseTool):
    name = "ping"
    description = "Return a pong."
    parameters = []

    def execute(self) -> str:
        return "pong"


class TestToolParam:
    def test_required_default(self):
        p = ToolParam("x", "string", "desc")
        assert p.required is True

    def test_optional_param(self):
        p = ToolParam("x", "string", "desc", required=False)
        assert p.required is False


class TestBaseToolSchema:
    def test_schema_structure(self):
        tool = EchoTool()
        schema = tool.to_llm_schema()
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == "echo"
        assert fn["description"] == "Echo back the input text."
        assert fn["parameters"]["type"] == "object"

    def test_required_params_listed(self):
        tool = EchoTool()
        schema = tool.to_llm_schema()
        required = schema["function"]["parameters"]["required"]
        assert "text" in required
        assert "prefix" not in required

    def test_properties_contain_type_and_description(self):
        tool = EchoTool()
        schema = tool.to_llm_schema()
        props = schema["function"]["parameters"]["properties"]
        assert props["text"]["type"] == "string"
        assert "Text to echo" in props["text"]["description"]
        assert "prefix" in props

    def test_no_params_tool_schema(self):
        tool = NoParamTool()
        schema = tool.to_llm_schema()
        assert schema["function"]["parameters"]["properties"] == {}
        assert schema["function"]["parameters"]["required"] == []

    def test_execute(self):
        tool = EchoTool()
        assert tool.execute("hello") == "hello"
        assert tool.execute("hello", ">> ") == ">> hello"


class TestToolRegistry:
    def setup_method(self):
        self.registry = ToolRegistry()
        self.echo = EchoTool()
        self.ping = NoParamTool()

    def test_register_and_get(self):
        self.registry.register(self.echo)
        retrieved = self.registry.get("echo")
        assert retrieved is self.echo

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError, match="unknown_tool"):
            self.registry.get("unknown_tool")

    def test_all_schemas_empty(self):
        assert self.registry.all_schemas() == []

    def test_all_schemas_returns_all(self):
        self.registry.register(self.echo)
        self.registry.register(self.ping)
        schemas = self.registry.all_schemas()
        names = {s["function"]["name"] for s in schemas}
        assert names == {"echo", "ping"}

    def test_execute_dispatches(self):
        self.registry.register(self.echo)
        result = self.registry.execute("echo", {"text": "world"})
        assert result == "world"

    def test_execute_with_optional_arg(self):
        self.registry.register(self.echo)
        result = self.registry.execute("echo", {"text": "world", "prefix": "→ "})
        assert result == "→ world"

    def test_execute_no_params_tool(self):
        self.registry.register(self.ping)
        result = self.registry.execute("ping", {})
        assert result == "pong"

    def test_execute_unknown_tool_raises(self):
        with pytest.raises(KeyError):
            self.registry.execute("does_not_exist", {})

    def test_register_overwrites_same_name(self):
        class AltEcho(BaseTool):
            name = "echo"
            description = "Alt"
            parameters = []

            def execute(self) -> str:
                return "alt"

        self.registry.register(self.echo)
        self.registry.register(AltEcho())
        assert self.registry.get("echo").description == "Alt"


class TestTimerTool:
    def test_schema_name(self):
        tool = TimerTool()
        schema = tool.to_llm_schema()
        assert schema["function"]["name"] == "set_timer"

    def test_minutes_param_required(self):
        tool = TimerTool()
        schema = tool.to_llm_schema()
        required = schema["function"]["parameters"]["required"]
        assert "minutes" in required

    def test_label_param_optional(self):
        tool = TimerTool()
        schema = tool.to_llm_schema()
        required = schema["function"]["parameters"]["required"]
        assert "label" not in required

    def test_execute_returns_confirmation_string(self):
        tool = TimerTool()
        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            result = tool.execute(minutes=5, label="focus")
        assert "5" in result
        assert "focus" in result

    def test_execute_starts_background_thread(self):
        tool = TimerTool()
        threads_started = []

        original_thread = threading.Thread

        def capture_thread(*args, **kwargs):
            t = original_thread(*args, **kwargs)
            threads_started.append(t)
            return t

        with patch("agents.tools.timer_tool.threading.Thread", side_effect=capture_thread):
            tool.execute(minutes=0, label="test")

        assert len(threads_started) == 1
        assert threads_started[0].daemon is True

    def test_on_speak_called_on_completion(self):
        on_speak = MagicMock()
        tool = TimerTool(on_speak=on_speak)
        # Use 0 minutes so the timer fires immediately
        tool._run(0, "test")
        assert on_speak.call_count == 2  # start + complete announcements

    def test_default_on_speak_is_logger(self):
        # Should not raise even without on_speak
        tool = TimerTool()
        tool._run(0, "test")

    def test_execute_default_label(self):
        tool = TimerTool()
        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            result = tool.execute(minutes=10)
        assert "timer" in result.lower()
