"""Unit tests for agents/subagents/dependency_subagent.py"""

import json
from unittest.mock import patch, MagicMock

import pytest

from agents.subagents.dependency_subagent import (
    DependencySubAgent,
    _parse_requirements,
    _installed_packages,
)


# ---------------------------------------------------------------------------
# _parse_requirements
# ---------------------------------------------------------------------------

class TestParseRequirements:
    def test_basic(self):
        text = "numpy>=1.20\nflask==2.3.0\n"
        parsed = _parse_requirements(text)
        names = [p["name"] for p in parsed]
        assert "numpy" in names
        assert "flask" in names

    def test_skips_comments_and_blank(self):
        text = "# comment\n\nnumpy\n"
        parsed = _parse_requirements(text)
        assert len(parsed) == 1

    def test_skips_dash_lines(self):
        text = "-r other.txt\nnumpy\n"
        parsed = _parse_requirements(text)
        assert len(parsed) == 1

    def test_returns_specifier(self):
        parsed = _parse_requirements("numpy>=1.20,<2.0")
        assert "1.20" in parsed[0]["specifier"] or "1.20" in parsed[0]["raw"]


# ---------------------------------------------------------------------------
# DependencySubAgent.execute
# ---------------------------------------------------------------------------

INSTALLED = {
    "numpy": "1.24.0",
    "flask": "2.3.3",
    "pyyaml": "6.0",
}


class TestDependencySubAgentExecute:
    @pytest.fixture
    def agent(self):
        return DependencySubAgent(orchestrator=None, paths=None)

    @patch("agents.subagents.dependency_subagent._installed_packages", return_value=INSTALLED)
    def test_all_ok(self, mock_installed, agent):
        result = json.loads(agent.execute("numpy>=1.20\nflask\n"))
        assert len(result["conflicts"]) == 0
        assert len(result["new"]) == 0
        assert any("numpy" in s for s in result["ok"])

    @patch("agents.subagents.dependency_subagent._installed_packages", return_value=INSTALLED)
    def test_new_package(self, mock_installed, agent):
        result = json.loads(agent.execute("some-new-lib>=1.0\n"))
        assert len(result["new"]) == 1
        assert "some-new-lib" in result["new"][0]

    @patch("agents.subagents.dependency_subagent._installed_packages", return_value=INSTALLED)
    def test_conflict_detected(self, mock_installed, agent):
        result = json.loads(agent.execute("numpy>=2.0\n"))
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["pkg"] == "numpy"
        assert result["conflicts"][0]["installed"] == "1.24.0"

    @patch("agents.subagents.dependency_subagent._installed_packages", return_value=INSTALLED)
    def test_no_specifier_is_ok(self, mock_installed, agent):
        result = json.loads(agent.execute("flask\n"))
        assert len(result["conflicts"]) == 0
        assert any("flask" in s for s in result["ok"])

    @patch("agents.subagents.dependency_subagent._installed_packages", return_value=INSTALLED)
    def test_empty_requirements(self, mock_installed, agent):
        result = json.loads(agent.execute(""))
        assert result == {"ok": [], "conflicts": [], "new": []}

    def test_metadata(self):
        agent = DependencySubAgent()
        assert agent.slug == "dependency"
        assert agent.display_name == "Dependency Manager"
        assert agent.name == "check_requirements"

    def test_additional_tools(self):
        agent = DependencySubAgent()
        tools = agent.get_additional_tools()
        tool_names = [t.name for t in tools]
        assert "list_installed" in tool_names
        assert "reconcile_requirements" in tool_names


# ---------------------------------------------------------------------------
# _ReconcileTool
# ---------------------------------------------------------------------------

class TestReconcileTool:
    @pytest.fixture
    def tool(self):
        from agents.subagents.dependency_subagent import _ReconcileTool
        return _ReconcileTool()

    def test_merge_disjoint(self, tool):
        base = "numpy>=1.20\n"
        addon = "flask==2.3.0\n"
        result = tool.execute(base_requirements=base, addon_requirements=addon)
        assert "numpy" in result
        assert "flask" in result

    def test_no_conflict_same_specifier(self, tool):
        base = "numpy>=1.20\n"
        addon = "numpy>=1.20\n"
        result = tool.execute(base_requirements=base, addon_requirements=addon)
        assert "CONFLICT" not in result

    def test_addon_no_specifier_keeps_base(self, tool):
        base = "numpy>=1.20\n"
        addon = "numpy\n"
        result = tool.execute(base_requirements=base, addon_requirements=addon)
        # base specifier should be preserved
        assert "numpy" in result
