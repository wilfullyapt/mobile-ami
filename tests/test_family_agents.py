"""
Unit tests for the family agents and their tools.

All LLM, TTS, and filesystem interactions are mocked — no hardware required.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.tools.tool_registry import ToolRegistry
from agents.tools.calendar_tool import CalendarAddTool, CalendarQueryTool
from agents.tools.shopping_tool import ShoppingAddTool, ShoppingQueryTool, ShoppingDoneTool
from agents.tools.message_tool import MessageLeaveTool, MessageReadTool
from agents.family_scheduler_agent import FamilySchedulerAgent
from agents.shopping_list_agent import ShoppingListAgent
from agents.kids_story_agent import KidsStoryAgent
from agents.morning_briefing_agent import MorningBriefingAgent
from agents.family_intercom_agent import FamilyIntercomAgent
from core.ami_paths import AmiPaths
from core.model_registry import ModelRole


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def ami_paths(tmp_path):
    paths = AmiPaths(root=str(tmp_path / "amini"))
    paths.ensure_dirs()
    return paths


def _make_llm(response="ok", tool_calls=None):
    llm = MagicMock()
    llm.chat_with_tools.return_value = (response, tool_calls or [])
    llm.chat.return_value = response
    return llm


def _make_orchestrator(llm=None, tts=None):
    orch = MagicMock()
    _llm = llm or _make_llm()
    _tts = tts or MagicMock()
    orch.get.side_effect = lambda role: {ModelRole.LLM: _llm, ModelRole.TTS: _tts}[role]
    return orch, _llm, _tts


# ---------------------------------------------------------------------------
# CalendarAddTool
# ---------------------------------------------------------------------------

class TestCalendarAddTool:
    def test_add_event_returns_confirmation(self, tmp_path):
        path = tmp_path / "calendar.json"
        tool = CalendarAddTool(path)
        result = tool.execute(title="Soccer practice", date="2026-03-10", person="Jake")
        assert "Soccer practice" in result
        assert "Jake" in result

    def test_add_event_persists_to_disk(self, tmp_path):
        path = tmp_path / "calendar.json"
        tool = CalendarAddTool(path)
        tool.execute(title="Dentist", date="2026-03-15")
        events = json.loads(path.read_text())
        assert any(e["title"] == "Dentist" for e in events)

    def test_add_multiple_events(self, tmp_path):
        path = tmp_path / "calendar.json"
        tool = CalendarAddTool(path)
        tool.execute(title="Event A", date="2026-03-10")
        tool.execute(title="Event B", date="2026-03-11")
        events = json.loads(path.read_text())
        assert len(events) == 2


class TestCalendarQueryTool:
    def test_returns_empty_message_when_no_events(self, tmp_path):
        path = tmp_path / "calendar.json"
        tool = CalendarQueryTool(path)
        result = tool.execute()
        assert "empty" in result.lower()

    def test_returns_events_in_date_range(self, tmp_path):
        path = tmp_path / "calendar.json"
        add = CalendarAddTool(path)
        add.execute("A", "2026-03-10")
        add.execute("B", "2026-04-01")
        query = CalendarQueryTool(path)
        result = query.execute(date_from="2026-03-01", date_to="2026-03-31")
        assert "A" in result
        assert "B" not in result

    def test_filter_by_person(self, tmp_path):
        path = tmp_path / "calendar.json"
        add = CalendarAddTool(path)
        add.execute("Jake Soccer", "2026-03-10", person="Jake")
        add.execute("Mom Yoga", "2026-03-10", person="Mom")
        query = CalendarQueryTool(path)
        result = query.execute(person="Jake")
        assert "Jake Soccer" in result
        assert "Mom Yoga" not in result


# ---------------------------------------------------------------------------
# ShoppingList tools
# ---------------------------------------------------------------------------

class TestShoppingTools:
    def test_add_and_query(self, tmp_path):
        path = tmp_path / "list.json"
        add = ShoppingAddTool(path)
        query = ShoppingQueryTool(path)
        add.execute("milk")
        add.execute("eggs", quantity="6")
        result = query.execute()
        assert "milk" in result.lower()
        assert "eggs" in result.lower()

    def test_add_duplicate_rejected(self, tmp_path):
        path = tmp_path / "list.json"
        tool = ShoppingAddTool(path)
        tool.execute("milk")
        result = tool.execute("milk")
        assert "already" in result.lower()

    def test_done_marks_item(self, tmp_path):
        path = tmp_path / "list.json"
        ShoppingAddTool(path).execute("bread")
        ShoppingDoneTool(path).execute("bread")
        items = json.loads(path.read_text())
        assert all(i["done"] for i in items if i["item"] == "bread")

    def test_done_nonexistent_item(self, tmp_path):
        path = tmp_path / "list.json"
        result = ShoppingDoneTool(path).execute("unicorn milk")
        assert "not found" in result.lower()

    def test_query_empty_list(self, tmp_path):
        path = tmp_path / "list.json"
        result = ShoppingQueryTool(path).execute()
        assert "empty" in result.lower()

    def test_done_items_excluded_from_query(self, tmp_path):
        path = tmp_path / "list.json"
        ShoppingAddTool(path).execute("apples")
        ShoppingDoneTool(path).execute("apples")
        result = ShoppingQueryTool(path).execute()
        assert "empty" in result.lower()


# ---------------------------------------------------------------------------
# Message tools
# ---------------------------------------------------------------------------

class TestMessageTools:
    def test_leave_and_read_message(self, tmp_path):
        msg_dir = tmp_path / "messages"
        leave = MessageLeaveTool(msg_dir)
        read = MessageReadTool(msg_dir)
        leave.execute(recipient="Mom", text="Dinner is in the fridge", sender="Jake")
        result = read.execute(recipient="Mom")
        assert "Dinner is in the fridge" in result
        assert "Jake" in result

    def test_read_marks_messages_as_read(self, tmp_path):
        msg_dir = tmp_path / "messages"
        MessageLeaveTool(msg_dir).execute("Mom", "Hello", "Jake")
        MessageReadTool(msg_dir).execute("Mom")
        # Second read should report no new messages
        result = MessageReadTool(msg_dir).execute("Mom")
        assert "No new messages" in result

    def test_read_empty_inbox(self, tmp_path):
        msg_dir = tmp_path / "messages"
        result = MessageReadTool(msg_dir).execute("Nobody")
        assert "No new messages" in result

    def test_leave_message_creates_inbox(self, tmp_path):
        msg_dir = tmp_path / "messages"
        MessageLeaveTool(msg_dir).execute("Dad", "Call me", "Mom")
        inbox = msg_dir / "dad" / "inbox.json"
        assert inbox.exists()


# ---------------------------------------------------------------------------
# FamilySchedulerAgent
# ---------------------------------------------------------------------------

class TestFamilySchedulerAgent:
    def _make(self, ami_paths, llm=None, tool_calls=None):
        _llm = llm or _make_llm("ok", tool_calls)
        orch, llm_inst, tts = _make_orchestrator(_llm)
        registry = ToolRegistry()
        agent = FamilySchedulerAgent(orch, registry, ami_paths)
        # Register the agent's tools in the registry so tool execution works
        for tool in agent.get_tools():
            registry.register(tool)
        return agent

    def test_llm_response_returned_when_no_tool_calls(self, ami_paths):
        agent = self._make(ami_paths, llm=_make_llm("Nothing scheduled today."))
        result = agent.process("What's on today?")
        assert result == "Nothing scheduled today."

    def test_tool_call_result_returned(self, ami_paths):
        tool_call = {"name": "calendar_add", "args": {"title": "Team meeting", "date": "2026-03-10"}}
        llm = _make_llm("", [tool_call])
        agent = self._make(ami_paths, llm=llm)
        result = agent.process("Add team meeting on March 10th")
        assert "Team meeting" in result

    def test_process_with_speaker(self, ami_paths):
        agent = self._make(ami_paths, llm=_make_llm("Your schedule is clear."))
        result = agent.process("What's on today?", speaker="Mom")
        assert result == "Your schedule is clear."

    def test_no_paths_returns_empty_tools(self, ami_paths):
        orch, _, _ = _make_orchestrator()
        agent = FamilySchedulerAgent(orch, ToolRegistry(), paths=None)
        assert agent.get_tools() == []


# ---------------------------------------------------------------------------
# ShoppingListAgent
# ---------------------------------------------------------------------------

class TestShoppingListAgent:
    def _make(self, ami_paths, llm=None, tool_calls=None):
        _llm = llm or _make_llm("ok", tool_calls)
        orch, _, _ = _make_orchestrator(_llm)
        registry = ToolRegistry()
        agent = ShoppingListAgent(orch, registry, ami_paths)
        for tool in agent.get_tools():
            registry.register(tool)
        return agent

    def test_returns_llm_response_on_no_tool_call(self, ami_paths):
        agent = self._make(ami_paths, llm=_make_llm("The list is empty."))
        result = agent.process("What's on the list?")
        assert result == "The list is empty."

    def test_tool_result_returned_on_add(self, ami_paths):
        tool_call = {"name": "shopping_add", "args": {"item": "milk"}}
        agent = self._make(ami_paths, llm=_make_llm("", [tool_call]))
        result = agent.process("Add milk")
        assert "milk" in result.lower()


# ---------------------------------------------------------------------------
# KidsStoryAgent
# ---------------------------------------------------------------------------

class TestKidsStoryAgent:
    def _make(self, llm=None):
        _llm = llm or _make_llm("Once upon a time…")
        orch, _, _ = _make_orchestrator(_llm)
        return KidsStoryAgent(orch, ToolRegistry())

    def test_returns_story_text(self):
        agent = self._make()
        result = agent.process("Tell me a story about a dragon")
        assert len(result) > 0

    def test_new_story_clears_context(self):
        agent = self._make()
        agent.process("Tell me a story about a cat")
        old_len = len(agent._story_messages)
        agent.process("Tell me a story about a dragon")  # triggers reset
        # After reset + one user turn, should be back to small count
        assert len(agent._story_messages) <= old_len

    def test_fallback_on_empty_llm_response(self):
        agent = self._make(llm=_make_llm(""))
        result = agent.process("Tell me a story")
        assert len(result) > 0  # fallback text used

    def test_speaker_addressed_in_system_prompt(self):
        llm = _make_llm("A story begins…")
        orch, llm_inst, _ = _make_orchestrator(llm)
        agent = KidsStoryAgent(orch, ToolRegistry())
        agent.process("Tell me a story", speaker="Zara")
        # Check that the system message includes the speaker's name
        system_content = agent._story_messages[0]["content"]
        assert "Zara" in system_content

    def test_story_context_trimmed_on_long_session(self):
        agent = self._make()
        for i in range(15):
            agent.process(f"what happens next {i}")
        # Should never exceed _MAX_STORY_SEGMENTS * 2 + 1 (system)
        assert len(agent._story_messages) <= 8 * 2 + 1


# ---------------------------------------------------------------------------
# MorningBriefingAgent
# ---------------------------------------------------------------------------

class TestMorningBriefingAgent:
    def _make(self, ami_paths, llm_response="Good morning!"):
        llm = _make_llm(llm_response)
        orch, _, _ = _make_orchestrator(llm)
        return MorningBriefingAgent(orch, ToolRegistry(), ami_paths)

    def test_returns_llm_response(self, ami_paths):
        agent = self._make(ami_paths)
        result = agent.process("Good morning")
        assert result == "Good morning!"

    def test_fallback_when_llm_returns_empty(self, ami_paths):
        llm = _make_llm("")
        orch, _, _ = _make_orchestrator(llm)
        agent = MorningBriefingAgent(orch, ToolRegistry(), ami_paths)
        result = agent.process("Good morning", speaker="Mom")
        assert "morning" in result.lower()
        assert "Mom" in result

    def test_reads_todays_events(self, ami_paths):
        from datetime import date
        today = date.today().isoformat()
        cal_path = ami_paths.data_dir / "calendar.json"
        cal_path.write_text(json.dumps([
            {"title": "School run", "date": today, "time": "08:00", "person": "Mom", "notes": ""}
        ]))
        agent = self._make(ami_paths)
        # Just verify it doesn't crash and returns a result
        result = agent.process("What's my day?", speaker="Mom")
        assert len(result) > 0

    def test_reads_unread_messages(self, ami_paths):
        from agents.tools.message_tool import MessageLeaveTool
        leave = MessageLeaveTool(ami_paths.data_dir / "messages")
        leave.execute("Dad", "Call the school", "Mom")
        agent = self._make(ami_paths)
        result = agent.process("Morning briefing", speaker="Dad")
        assert len(result) > 0


# ---------------------------------------------------------------------------
# FamilyIntercomAgent
# ---------------------------------------------------------------------------

class TestFamilyIntercomAgent:
    def _make(self, ami_paths, llm=None, tool_calls=None):
        _llm = llm or _make_llm("ok", tool_calls)
        orch, _, _ = _make_orchestrator(_llm)
        registry = ToolRegistry()
        agent = FamilyIntercomAgent(orch, registry, ami_paths)
        for tool in agent.get_tools():
            registry.register(tool)
        return agent

    def test_leave_message_via_tool(self, ami_paths):
        tool_call = {
            "name": "message_leave",
            "args": {"recipient": "Mom", "text": "Dinner is ready"},
        }
        agent = self._make(ami_paths, llm=_make_llm("", [tool_call]))
        result = agent.process("Leave a message for Mom: dinner is ready", speaker="Jake")
        assert "Mom" in result

    def test_auto_injects_sender_from_speaker(self, ami_paths):
        """The agent should inject speaker name as sender if not already set."""
        captured_args = {}

        registry = ToolRegistry()
        orch, llm_inst, _ = _make_orchestrator(_make_llm("", [{
            "name": "message_leave",
            "args": {"recipient": "Mom", "text": "Hi"},
        }]))
        agent = FamilyIntercomAgent(orch, registry, ami_paths)

        # Capture the args passed to execute
        original_execute = registry.execute

        def capturing_execute(name, args):
            if name == "message_leave":
                captured_args.update(args)
            return "Message left for Mom."

        registry.execute = capturing_execute
        for tool in agent.get_tools():
            registry.register(tool)

        agent.process("Leave a message for Mom: Hi", speaker="Jake")
        assert captured_args.get("sender") == "Jake"

    def test_rewrites_my_messages_query_with_speaker(self, ami_paths):
        """'Do I have any messages?' → 'Read messages for <speaker>'"""
        llm = MagicMock()
        llm.chat_with_tools.return_value = ("No new messages.", [])
        orch, _, _ = _make_orchestrator(llm)
        registry = ToolRegistry()
        agent = FamilyIntercomAgent(orch, registry, ami_paths)
        for tool in agent.get_tools():
            registry.register(tool)

        agent.process("Do I have any messages?", speaker="Jake")
        # The text passed to LLM should be rewritten
        call_messages = llm.chat_with_tools.call_args[0][0]
        user_msg = next(m for m in call_messages if m["role"] == "user")
        assert "Jake" in user_msg["content"]

    def test_no_paths_returns_empty_tools(self):
        orch, _, _ = _make_orchestrator()
        agent = FamilyIntercomAgent(orch, ToolRegistry(), paths=None)
        assert agent.get_tools() == []


# ---------------------------------------------------------------------------
# Pipeline integration: speaker passed to agents
# ---------------------------------------------------------------------------

class TestPipelinePassesSpeaker:
    """Verify that the pipeline passes the identified speaker to agent.process()."""

    def test_process_called_with_speaker(self):
        from core.pipeline import VoicePipeline, PipelineContext
        from core.model_registry import ModelRole
        import numpy as np

        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = "hello"
        mock_tts = MagicMock()
        mock_vad = MagicMock()
        mock_wake = MagicMock()
        orch = MagicMock()
        orch.get.side_effect = lambda role: {
            ModelRole.STT: mock_stt,
            ModelRole.TTS: mock_tts,
            ModelRole.VAD: mock_vad,
            ModelRole.WAKE: mock_wake,
        }[role]
        orch.has.return_value = False  # no speaker model — skip identification

        audio_mgr = MagicMock()
        audio_mgr.record_until_silence.return_value = np.zeros(16000, dtype=np.float32)

        agent = MagicMock()
        agent.process.return_value = "response"
        agent_mgr = MagicMock()
        agent_mgr.get_current_agent.return_value = agent
        agent_mgr.current = "qa"

        pipeline = VoicePipeline(
            orchestrator=orch,
            agent_manager=agent_mgr,
            audio=audio_mgr,
            leds=MagicMock(),
            on_speak=MagicMock(),
        )
        ctx = pipeline.run_once()

        # With no speaker profiles, speaker should be None
        agent.process.assert_called_once_with("hello", speaker=None)
