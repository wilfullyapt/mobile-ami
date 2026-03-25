"""Unit tests for agents/subagents/ally/soul_tools_subagent.py"""

import json
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def soul_manager(tmp_path):
    """A real SoulManager backed by a tmp dir."""
    from core.ami_paths import AmiPaths
    from core.ally.soul import SoulManager

    paths = MagicMock()
    paths.soul_path = tmp_path / "soul.md"
    paths.soul_update_path = tmp_path / "soul_update.json"
    # Write initial soul content
    paths.soul_path.write_text("## Identity\nAmi.\n\n## Purpose\nHelp.\n\n")
    return SoulManager.__new__(SoulManager), paths


@pytest.fixture
def soul_mgr(tmp_path):
    """Convenience: returns a SoulManager instance."""
    from core.ally.soul import SoulManager
    paths = MagicMock()
    paths.soul_path = tmp_path / "soul.md"
    paths.soul_update_path = tmp_path / "soul_update.json"
    paths.soul_path.write_text("## Identity\nAmi.\n\n## Purpose\nHelp.\n\n")

    mgr = SoulManager.__new__(SoulManager)
    from core.ally.soul_section_manager import SoulSectionManager
    mgr._path = paths.soul_path
    mgr._update_path = paths.soul_update_path
    mgr._ssm = SoulSectionManager()
    return mgr


# ---------------------------------------------------------------------------
# SoulListSectionsTool
# ---------------------------------------------------------------------------

class TestSoulListSectionsTool:
    def test_returns_json_array(self, soul_mgr):
        from agents.subagents.ally.soul_tools_subagent import SoulListSectionsTool
        tool = SoulListSectionsTool(soul_mgr)
        result = tool.execute()
        data = json.loads(result)
        assert isinstance(data, list)
        headings = [d["heading"] for d in data]
        assert "Identity" in headings
        assert "Purpose" in headings

    def test_includes_level(self, soul_mgr):
        from agents.subagents.ally.soul_tools_subagent import SoulListSectionsTool
        tool = SoulListSectionsTool(soul_mgr)
        data = json.loads(tool.execute())
        for item in data:
            assert "level" in item


# ---------------------------------------------------------------------------
# SoulUpdateSectionTool
# ---------------------------------------------------------------------------

class TestSoulUpdateSectionTool:
    def test_updates_existing_section(self, soul_mgr):
        from agents.subagents.ally.soul_tools_subagent import SoulUpdateSectionTool
        tool = SoulUpdateSectionTool(soul_mgr)
        result = tool.execute(section="Purpose", content="New purpose text.")
        assert "Updated" in result
        assert "New purpose text." in soul_mgr.read()

    def test_creates_missing_section(self, soul_mgr):
        from agents.subagents.ally.soul_tools_subagent import SoulUpdateSectionTool
        tool = SoulUpdateSectionTool(soul_mgr)
        tool.execute(section="Growth Notes", content="Growing steadily.")
        assert "Growth Notes" in soul_mgr.read()

    def test_writes_soul_update_json(self, soul_mgr, tmp_path):
        from agents.subagents.ally.soul_tools_subagent import SoulUpdateSectionTool
        tool = SoulUpdateSectionTool(soul_mgr)
        tool.execute(section="Purpose", content="New.")
        update_path = tmp_path / "soul_update.json"
        assert update_path.exists()
        data = json.loads(update_path.read_text())
        assert data["operation"] == "update"


# ---------------------------------------------------------------------------
# SoulAddSectionTool
# ---------------------------------------------------------------------------

class TestSoulAddSectionTool:
    def test_add_section(self, soul_mgr):
        from agents.subagents.ally.soul_tools_subagent import SoulAddSectionTool
        tool = SoulAddSectionTool(soul_mgr)
        result = tool.execute(section="Growth Notes", content="First note.")
        assert "Added" in result
        assert "Growth Notes" in soul_mgr.read()

    def test_add_after_existing(self, soul_mgr):
        from agents.subagents.ally.soul_tools_subagent import SoulAddSectionTool
        tool = SoulAddSectionTool(soul_mgr)
        tool.execute(section="Middle", content="Middle content.", after="Identity")
        content = soul_mgr.read()
        identity_pos = content.index("Identity")
        middle_pos = content.index("Middle")
        purpose_pos = content.index("Purpose")
        assert identity_pos < middle_pos < purpose_pos

    def test_add_custom_level(self, soul_mgr):
        from agents.subagents.ally.soul_tools_subagent import SoulAddSectionTool
        tool = SoulAddSectionTool(soul_mgr)
        tool.execute(section="Notes", content="A note.", level=3)
        assert "### Notes" in soul_mgr.read()


# ---------------------------------------------------------------------------
# SoulRemoveSectionTool
# ---------------------------------------------------------------------------

class TestSoulRemoveSectionTool:
    def test_remove_existing(self, soul_mgr):
        from agents.subagents.ally.soul_tools_subagent import SoulRemoveSectionTool
        tool = SoulRemoveSectionTool(soul_mgr)
        result = tool.execute(section="Purpose")
        assert "Removed" in result
        assert "Purpose" not in soul_mgr.get_headings()

    def test_remove_nonexistent_no_error(self, soul_mgr):
        from agents.subagents.ally.soul_tools_subagent import SoulRemoveSectionTool
        tool = SoulRemoveSectionTool(soul_mgr)
        result = tool.execute(section="Nonexistent")
        assert "Removed" in result  # returns success even for no-op


# ---------------------------------------------------------------------------
# SoulReorderSectionsTool
# ---------------------------------------------------------------------------

class TestSoulReorderSectionsTool:
    def test_reorder_sections(self, soul_mgr):
        from agents.subagents.ally.soul_tools_subagent import SoulReorderSectionsTool
        tool = SoulReorderSectionsTool(soul_mgr)
        result = tool.execute(order=json.dumps(["Purpose", "Identity"]))
        assert "Reordered" in result
        headings = soul_mgr.get_headings()
        assert headings[0] == "Purpose"
        assert headings[1] == "Identity"

    def test_invalid_json_returns_error(self, soul_mgr):
        from agents.subagents.ally.soul_tools_subagent import SoulReorderSectionsTool
        tool = SoulReorderSectionsTool(soul_mgr)
        result = tool.execute(order="not valid json")
        assert "Error" in result

    def test_non_list_json_returns_error(self, soul_mgr):
        from agents.subagents.ally.soul_tools_subagent import SoulReorderSectionsTool
        tool = SoulReorderSectionsTool(soul_mgr)
        result = tool.execute(order=json.dumps({"a": 1}))
        assert "Error" in result
