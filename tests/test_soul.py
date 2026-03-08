"""Unit tests for core/soul.py"""

import pytest
from datetime import date
from core.soul import SoulManager
from core.ami_paths import AmiPaths


@pytest.fixture
def paths(tmp_path):
    p = AmiPaths(root=str(tmp_path / "amini"))
    p.ensure_dirs()
    return p


class TestSoulManagerRead:
    def test_returns_searching_template_when_no_file_and_no_owner(self, paths):
        soul = SoulManager(paths)
        content = soul.read(has_owner=False)
        assert "SEARCHING" in content.upper() or "searching" in content.lower()

    def test_returns_serving_template_when_no_file_but_owner(self, paths):
        soul = SoulManager(paths)
        content = soul.read(has_owner=True)
        assert "Soul" in content

    def test_returns_file_content_when_exists(self, paths):
        paths.soul_path.write_text("# My Custom Soul\nHello world")
        soul = SoulManager(paths)
        assert soul.read() == "# My Custom Soul\nHello world"

    def test_exists_false_before_creation(self, paths):
        soul = SoulManager(paths)
        assert soul.exists() is False

    def test_exists_true_after_creation(self, paths):
        soul = SoulManager(paths)
        soul.create_for_owner("Alice")
        assert soul.exists() is True


class TestSoulManagerCreate:
    def test_create_for_owner_writes_file(self, paths):
        soul = SoulManager(paths)
        soul.create_for_owner("Alice")
        assert paths.soul_path.exists()

    def test_create_for_owner_includes_name(self, paths):
        soul = SoulManager(paths)
        soul.create_for_owner("Alice")
        content = paths.soul_path.read_text()
        assert "Alice" in content

    def test_create_for_owner_includes_date(self, paths):
        soul = SoulManager(paths)
        soul.create_for_owner("Alice")
        content = paths.soul_path.read_text()
        assert date.today().isoformat() in content

    def test_create_for_owner_includes_purpose(self, paths):
        soul = SoulManager(paths)
        soul.create_for_owner("Alice", purpose="Help me stay focused.")
        content = paths.soul_path.read_text()
        assert "Help me stay focused." in content

    def test_create_overwrites_existing(self, paths):
        soul = SoulManager(paths)
        soul.create_for_owner("Alice")
        soul.create_for_owner("Bob")
        content = paths.soul_path.read_text()
        assert "Bob" in content
        assert "Alice" not in content


class TestSoulManagerDailyNotes:
    def test_append_daily_notes_creates_section(self, paths):
        soul = SoulManager(paths)
        soul.create_for_owner("Alice")
        soul.append_daily_notes("- Alice discussed a new project.", date(2026, 3, 8))
        content = paths.soul_path.read_text()
        assert "2026-03-08" in content
        assert "Alice discussed a new project." in content

    def test_append_daily_notes_twice_keeps_both(self, paths):
        soul = SoulManager(paths)
        soul.create_for_owner("Alice")
        soul.append_daily_notes("- Note one.", date(2026, 3, 7))
        soul.append_daily_notes("- Note two.", date(2026, 3, 8))
        content = paths.soul_path.read_text()
        assert "Note one." in content
        assert "Note two." in content

    def test_write_raw_overwrites(self, paths):
        soul = SoulManager(paths)
        soul.write_raw("# Totally custom soul")
        assert paths.soul_path.read_text() == "# Totally custom soul"
