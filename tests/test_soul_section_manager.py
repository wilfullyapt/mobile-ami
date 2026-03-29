"""Unit tests for core/ally/soul_section_manager.py"""

import pytest
from core.ally.soul_section_manager import SoulSectionManager, SoulSection


@pytest.fixture
def ssm():
    return SoulSectionManager()


# ---------------------------------------------------------------------------
# parse + serialize round-trip
# ---------------------------------------------------------------------------

class TestParseSerialize:
    def test_empty_string(self, ssm):
        sections = ssm.parse("")
        assert sections == []
        assert ssm.serialize(sections) == ""

    def test_no_headings_is_preamble(self, ssm):
        text = "Just some text with no headings.\n"
        sections = ssm.parse(text)
        assert len(sections) == 1
        assert sections[0].heading is None
        assert sections[0].level == 0
        assert sections[0].content == text

    def test_single_h2_section(self, ssm):
        text = "## Identity\nYour name is Ami.\n"
        sections = ssm.parse(text)
        assert len(sections) == 1
        assert sections[0].heading == "Identity"
        assert sections[0].level == 2
        assert "Ami" in sections[0].content

    def test_h1_heading(self, ssm):
        text = "# Soul\n\nSome content.\n"
        sections = ssm.parse(text)
        assert sections[0].level == 1
        assert sections[0].heading == "Soul"

    def test_h3_heading(self, ssm):
        text = "### Deep Section\nContent here.\n"
        sections = ssm.parse(text)
        assert sections[0].level == 3

    def test_preamble_plus_sections(self, ssm):
        text = "Preamble line.\n\n## Identity\nContent A.\n\n## Purpose\nContent B.\n"
        sections = ssm.parse(text)
        assert sections[0].heading is None
        assert sections[1].heading == "Identity"
        assert sections[2].heading == "Purpose"

    def test_round_trip_exact(self, ssm):
        text = "# Soul\n\n## Identity\nYour name is Ami.\n\n## Purpose\nHelp the owner.\n"
        assert ssm.serialize(ssm.parse(text)) == text

    def test_mixed_heading_levels(self, ssm):
        text = "# Top\n## Sub\n### Deep\n"
        sections = ssm.parse(text)
        assert [s.level for s in sections] == [1, 2, 3]
        assert ssm.serialize(sections) == text

    def test_no_preamble_when_starts_with_heading(self, ssm):
        text = "## First\nContent.\n"
        sections = ssm.parse(text)
        assert sections[0].heading == "First"
        assert all(s.heading is not None for s in sections)


# ---------------------------------------------------------------------------
# list_headings + find
# ---------------------------------------------------------------------------

class TestListFind:
    def test_list_headings(self, ssm):
        text = "## A\ncontent\n## B\ncontent\n## C\ncontent\n"
        sections = ssm.parse(text)
        assert ssm.list_headings(sections) == ["A", "B", "C"]

    def test_list_headings_excludes_preamble(self, ssm):
        text = "Preamble.\n## A\ncontent\n"
        sections = ssm.parse(text)
        assert ssm.list_headings(sections) == ["A"]

    def test_find_existing(self, ssm):
        text = "## Identity\nContent.\n"
        sections = ssm.parse(text)
        found = ssm.find(sections, "Identity")
        assert found is not None
        assert found.heading == "Identity"

    def test_find_case_insensitive(self, ssm):
        text = "## Identity\nContent.\n"
        sections = ssm.parse(text)
        assert ssm.find(sections, "identity") is not None
        assert ssm.find(sections, "IDENTITY") is not None

    def test_find_not_found(self, ssm):
        sections = ssm.parse("## A\ncontent\n")
        assert ssm.find(sections, "Nonexistent") is None


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

class TestUpdate:
    def test_update_existing_section(self, ssm):
        text = "## Purpose\nOld purpose.\n"
        sections = ssm.parse(text)
        sections = ssm.update(sections, "Purpose", "New purpose.")
        assert "New purpose." in ssm.serialize(sections)
        assert "Old purpose." not in ssm.serialize(sections)

    def test_update_preserves_other_sections(self, ssm):
        text = "## A\nKeep me.\n## B\nOld B.\n"
        sections = ssm.parse(text)
        sections = ssm.update(sections, "B", "New B.")
        result = ssm.serialize(sections)
        assert "Keep me." in result
        assert "New B." in result

    def test_update_nonexistent_appends(self, ssm):
        text = "## A\nContent.\n"
        sections = ssm.parse(text)
        sections = ssm.update(sections, "NewSection", "New content.")
        headings = ssm.list_headings(sections)
        assert "NewSection" in headings

    def test_update_preserves_heading_level(self, ssm):
        text = "### DeepSection\nOld.\n"
        sections = ssm.parse(text)
        sections = ssm.update(sections, "DeepSection", "New.")
        found = ssm.find(sections, "DeepSection")
        assert found.level == 3


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

class TestAdd:
    def test_add_appends_by_default(self, ssm):
        sections = ssm.parse("## A\ncontent\n")
        sections = ssm.add(sections, "B", "B content.")
        assert ssm.list_headings(sections) == ["A", "B"]

    def test_add_after_existing(self, ssm):
        sections = ssm.parse("## A\ncontent\n## C\ncontent\n")
        sections = ssm.add(sections, "B", "B content.", after="A")
        assert ssm.list_headings(sections) == ["A", "B", "C"]

    def test_add_after_nonexistent_falls_back_to_append(self, ssm):
        sections = ssm.parse("## A\ncontent\n")
        sections = ssm.add(sections, "B", "B content.", after="Nonexistent")
        assert ssm.list_headings(sections) == ["A", "B"]

    def test_add_at_position(self, ssm):
        sections = ssm.parse("## A\ncontent\n## C\ncontent\n")
        sections = ssm.add(sections, "B", "B content.", position=1)
        assert ssm.list_headings(sections)[1] == "B"

    def test_add_custom_level(self, ssm):
        sections = ssm.parse("")
        sections = ssm.add(sections, "MySection", "Content.", level=3)
        assert "### MySection" in ssm.serialize(sections)

    def test_add_preamble_not_displaced(self, ssm):
        sections = ssm.parse("Preamble.\n## A\ncontent\n")
        sections = ssm.add(sections, "B", "B.", position=0)
        assert sections[0].heading is None  # preamble stays first


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

class TestRemove:
    def test_remove_existing(self, ssm):
        text = "## A\ncontent\n## B\ncontent\n"
        sections = ssm.parse(text)
        sections = ssm.remove(sections, "A")
        assert ssm.list_headings(sections) == ["B"]

    def test_remove_nonexistent_is_noop(self, ssm):
        text = "## A\ncontent\n"
        sections = ssm.parse(text)
        sections = ssm.remove(sections, "Nonexistent")
        assert ssm.list_headings(sections) == ["A"]

    def test_remove_does_not_touch_preamble(self, ssm):
        text = "Preamble.\n## A\ncontent\n"
        sections = ssm.parse(text)
        sections = ssm.remove(sections, "A")
        assert sections[0].heading is None


# ---------------------------------------------------------------------------
# reorder
# ---------------------------------------------------------------------------

class TestReorder:
    def test_basic_reorder(self, ssm):
        text = "## A\nc\n## B\nc\n## C\nc\n"
        sections = ssm.parse(text)
        sections = ssm.reorder(sections, ["C", "A", "B"])
        assert ssm.list_headings(sections) == ["C", "A", "B"]

    def test_unmentioned_appended_at_end(self, ssm):
        text = "## A\nc\n## B\nc\n## C\nc\n"
        sections = ssm.parse(text)
        sections = ssm.reorder(sections, ["B"])
        headings = ssm.list_headings(sections)
        assert headings[0] == "B"
        assert set(headings) == {"A", "B", "C"}

    def test_preamble_stays_first(self, ssm):
        text = "Preamble.\n## A\nc\n## B\nc\n"
        sections = ssm.parse(text)
        sections = ssm.reorder(sections, ["B", "A"])
        assert sections[0].heading is None

    def test_case_insensitive_reorder(self, ssm):
        text = "## Identity\nc\n## Purpose\nc\n"
        sections = ssm.parse(text)
        sections = ssm.reorder(sections, ["purpose", "identity"])
        headings = ssm.list_headings(sections)
        assert headings[0].lower() == "purpose"


# ---------------------------------------------------------------------------
# append_line
# ---------------------------------------------------------------------------

class TestAppendLine:
    def test_append_to_existing(self, ssm):
        text = "## Journal Entry Snapshot\n- 2026-01-01: work\n"
        sections = ssm.parse(text)
        sections = ssm.append_line(sections, "Journal Entry Snapshot", "- 2026-01-02: family")
        result = ssm.serialize(sections)
        assert "- 2026-01-01: work" in result
        assert "- 2026-01-02: family" in result

    def test_append_creates_section_if_missing(self, ssm):
        sections = ssm.parse("## A\ncontent\n")
        sections = ssm.append_line(sections, "NewSection", "- first line")
        assert "NewSection" in ssm.list_headings(sections)

    def test_append_does_not_strip_existing_lines(self, ssm):
        """Multiple appends accumulate correctly."""
        sections = ssm.parse("")
        sections = ssm.append_line(sections, "Log", "line 1")
        sections = ssm.append_line(sections, "Log", "line 2")
        sections = ssm.append_line(sections, "Log", "line 3")
        result = ssm.serialize(sections)
        assert "line 1" in result
        assert "line 2" in result
        assert "line 3" in result
