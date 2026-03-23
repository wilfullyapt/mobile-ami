"""Unit tests for AgentManager live-reload API (enable/disable/equip)."""

from unittest.mock import MagicMock, patch

import pytest

from core.agent_manager import AgentManager
from agents.tools.tool_registry import ToolRegistry, FilteredToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_agent(slug="mock"):
    agent = MagicMock()
    agent.on_entry = MagicMock()
    agent.on_exit = MagicMock()
    return agent


def _make_manager(slugs=None, config_data=None):
    """Build an AgentManager with mocked agent loading."""
    slugs = slugs or ["llm_response", "planning"]
    registry = ToolRegistry()
    orchestrator = MagicMock()

    cm = None
    if config_data is not None:
        cm = MagicMock()
        cm.get_agent_config = lambda slug: config_data.get(slug, {
            "enabled": True, "equipped_sub_agents": [],
        })

    instances = {s: _make_mock_agent(s) for s in slugs}

    with patch.object(AgentManager, "_load", side_effect=lambda slug, *a, **kw: instances[slug]):
        am = AgentManager(
            slugs=slugs,
            orchestrator=orchestrator,
            tool_registry=registry,
            config_manager=cm,
        )

    # Expose instances for assertions
    am._test_instances = instances
    am._test_registry = registry
    am._test_orchestrator = orchestrator
    return am


# ---------------------------------------------------------------------------
# Basic properties (regression)
# ---------------------------------------------------------------------------

class TestBasicProperties:
    def test_current(self):
        am = _make_manager(["llm_response", "planning"])
        assert am.current == "llm_response"

    def test_slugs(self):
        am = _make_manager(["llm_response", "planning"])
        assert set(am.slugs) == {"llm_response", "planning"}

    def test_cycle(self):
        am = _make_manager(["llm_response", "planning"])
        am.cycle()
        assert am.current == "planning"
        am.cycle()
        assert am.current == "llm_response"


# ---------------------------------------------------------------------------
# enable_agent
# ---------------------------------------------------------------------------

class TestEnableAgent:
    def test_enable_new_agent(self):
        am = _make_manager(["llm_response"])
        new_inst = _make_mock_agent("block_timer")
        with patch.object(am, "_load", return_value=new_inst):
            am.enable_agent("block_timer")
        assert "block_timer" in am.slugs

    def test_enable_already_active_is_noop(self):
        am = _make_manager(["llm_response", "planning"])
        original_len = len(am.slugs)
        am.enable_agent("llm_response")
        assert len(am.slugs) == original_len

    def test_enable_updates_config(self):
        am = _make_manager(["llm_response"])
        am._config_manager = MagicMock()
        new_inst = _make_mock_agent("block_timer")
        with patch.object(am, "_load", return_value=new_inst):
            am.enable_agent("block_timer")
        am._config_manager.set_agent_enabled.assert_called_once_with("block_timer", True)


# ---------------------------------------------------------------------------
# disable_agent
# ---------------------------------------------------------------------------

class TestDisableAgent:
    def test_disable_removes_from_slugs(self):
        am = _make_manager(["llm_response", "planning"])
        am.disable_agent("planning")
        assert "planning" not in am.slugs

    def test_disable_current_cycles_first(self):
        am = _make_manager(["llm_response", "planning"])
        # llm_response is current (index 0)
        am.disable_agent("llm_response")
        assert am.current == "planning"

    def test_disable_only_agent_raises(self):
        am = _make_manager(["llm_response"])
        with pytest.raises(ValueError):
            am.disable_agent("llm_response")

    def test_disable_absent_slug_is_noop(self):
        am = _make_manager(["llm_response", "planning"])
        am.disable_agent("nonexistent")  # should not raise
        assert len(am.slugs) == 2

    def test_disable_calls_on_exit(self):
        am = _make_manager(["llm_response", "planning"])
        agent_inst = am._instances["planning"]
        am.disable_agent("planning")
        agent_inst.on_exit.assert_called()

    def test_disable_updates_config(self):
        am = _make_manager(["llm_response", "planning"])
        am._config_manager = MagicMock()
        am.disable_agent("planning")
        am._config_manager.set_agent_enabled.assert_called_once_with("planning", False)


# ---------------------------------------------------------------------------
# update_equipped_sub_agents
# ---------------------------------------------------------------------------

class TestUpdateEquippedSubAgents:
    def test_creates_filtered_registry(self):
        am = _make_manager(["llm_response", "planning"])
        am.update_equipped_sub_agents("planning", ["memory", "timer"])
        assert "planning" in am._filtered_registries
        fr = am._filtered_registries["planning"]
        assert isinstance(fr, FilteredToolRegistry)

    def test_persists_to_config(self):
        am = _make_manager(["llm_response", "planning"])
        am._config_manager = MagicMock()
        am.update_equipped_sub_agents("planning", ["memory"])
        am._config_manager.set_agent_equipped_sub_agents.assert_called_once_with(
            "planning", ["memory"]
        )


# ---------------------------------------------------------------------------
# FilteredToolRegistry
# ---------------------------------------------------------------------------

class TestFilteredToolRegistry:
    def _make_sub_agent(self, slug, tool_name):
        from agents.base_sub_agent import BaseSubAgent
        sa = MagicMock(spec=BaseSubAgent)
        sa.slug = slug
        sa.name = tool_name
        sa.get_additional_tools = MagicMock(return_value=[])
        sa.to_llm_schema = MagicMock(return_value={
            "type": "function",
            "function": {"name": tool_name, "description": "", "parameters": {}},
        })
        return sa

    def _schema_name(self, s: dict) -> str:
        return s.get("function", {}).get("name", s.get("name", ""))

    def test_allows_equipped_tools(self):
        parent = ToolRegistry()
        mem_sa = self._make_sub_agent("memory", "memory_store")
        parent.register(mem_sa)
        parent._sub_agents["memory"] = mem_sa

        fr = FilteredToolRegistry(parent, {"memory"})
        schemas = fr.all_schemas()
        assert any(self._schema_name(s) == "memory_store" for s in schemas)

    def test_blocks_unequipped_tools(self):
        parent = ToolRegistry()
        timer_sa = self._make_sub_agent("timer", "set_timer")
        parent.register(timer_sa)
        parent._sub_agents["timer"] = timer_sa

        fr = FilteredToolRegistry(parent, set())  # nothing equipped
        schemas = fr.all_schemas()
        assert not any(self._schema_name(s) == "set_timer" for s in schemas)

    def test_update_allowed_slugs(self):
        parent = ToolRegistry()
        sa = self._make_sub_agent("memory", "memory_store")
        parent.register(sa)
        parent._sub_agents["memory"] = sa

        fr = FilteredToolRegistry(parent, set())  # start empty
        assert fr.all_schemas() == []

        fr.update_allowed_slugs({"memory"})
        assert any(self._schema_name(s) == "memory_store" for s in fr.all_schemas())

    def test_allows_tools_without_sub_agent(self):
        """Tools not associated with any sub-agent should always pass through."""
        from agents.tools.base_tool import BaseTool, ToolParam

        class _FreeTool(BaseTool):
            name = "free_tool"
            description = "unowned"
            parameters = []
            def execute(self): return "ok"

        parent = ToolRegistry()
        parent.register(_FreeTool())
        fr = FilteredToolRegistry(parent, set())
        schemas = fr.all_schemas()
        assert any(s.get("function", {}).get("name") == "free_tool" for s in schemas)
