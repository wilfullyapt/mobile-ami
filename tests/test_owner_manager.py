"""Unit tests for core/owner_manager.py"""

import json
import time
import pytest
from core.owner_manager import OwnerManager
from core.ami_paths import AmiPaths


@pytest.fixture
def paths(tmp_path):
    p = AmiPaths(root=str(tmp_path / "amini"))
    p.ensure_dirs()
    return p


class TestOwnerManagerNoOwner:
    def test_has_owner_false_initially(self, paths):
        mgr = OwnerManager(paths)
        assert mgr.has_owner is False

    def test_owner_name_is_none(self, paths):
        mgr = OwnerManager(paths)
        assert mgr.owner_name is None

    def test_established_at_is_none(self, paths):
        mgr = OwnerManager(paths)
        assert mgr.established_at is None

    def test_last_seen_is_none(self, paths):
        mgr = OwnerManager(paths)
        assert mgr.last_seen_at is None

    def test_seconds_since_seen_is_none(self, paths):
        mgr = OwnerManager(paths)
        assert mgr.seconds_since_owner_seen() is None

    def test_is_owner_present_false_without_owner(self, paths):
        mgr = OwnerManager(paths)
        assert mgr.is_owner_present() is False


class TestOwnerEstablishment:
    def test_establish_sets_owner_name(self, paths):
        mgr = OwnerManager(paths)
        mgr.establish("Alice")
        assert mgr.owner_name == "Alice"

    def test_establish_sets_has_owner(self, paths):
        mgr = OwnerManager(paths)
        mgr.establish("Alice")
        assert mgr.has_owner is True

    def test_establish_persists_to_disk(self, paths):
        mgr = OwnerManager(paths)
        mgr.establish("Bob")
        mgr2 = OwnerManager(paths)
        assert mgr2.owner_name == "Bob"

    def test_establish_sets_established_at(self, paths):
        mgr = OwnerManager(paths)
        mgr.establish("Alice")
        assert mgr.established_at is not None

    def test_establish_sets_last_seen_at(self, paths):
        mgr = OwnerManager(paths)
        mgr.establish("Alice")
        assert mgr.last_seen_at is not None

    def test_establish_idempotent_updates_name(self, paths):
        mgr = OwnerManager(paths)
        mgr.establish("Alice")
        mgr.establish("Bob")
        assert mgr.owner_name == "Bob"


class TestRecordSeen:
    def test_record_seen_updates_last_seen(self, paths):
        mgr = OwnerManager(paths)
        mgr.establish("Alice")
        before = mgr.last_seen_at
        time.sleep(0.01)
        mgr.record_seen("Alice")
        assert mgr.last_seen_at >= before

    def test_record_seen_noop_for_wrong_name(self, paths):
        mgr = OwnerManager(paths)
        mgr.establish("Alice")
        before = mgr.last_seen_at
        mgr.record_seen("Bob")  # not the owner
        assert mgr.last_seen_at == before

    def test_seconds_since_owner_seen_returns_float(self, paths):
        mgr = OwnerManager(paths)
        mgr.establish("Alice")
        secs = mgr.seconds_since_owner_seen()
        assert secs is not None
        assert secs >= 0.0

    def test_is_owner_present_true_when_recently_seen(self, paths):
        mgr = OwnerManager(paths)
        mgr.establish("Alice")
        mgr.record_seen("Alice")
        assert mgr.is_owner_present(within_sec=300) is True

    def test_is_owner_present_false_when_threshold_passed(self, paths):
        mgr = OwnerManager(paths)
        mgr.establish("Alice")
        # last_seen_at is set on establish; pretend it was a long time ago
        data = json.loads(paths.owner_path.read_text())
        # Set last_seen to epoch
        data["last_seen_at"] = "1970-01-01T00:00:00+00:00"
        paths.owner_path.write_text(json.dumps(data))
        mgr2 = OwnerManager(paths)
        assert mgr2.is_owner_present(within_sec=1) is False


class TestOwnerManagerCorruption:
    def test_corrupted_owner_file_loads_empty(self, paths):
        paths.owner_path.parent.mkdir(parents=True, exist_ok=True)
        paths.owner_path.write_text("NOT JSON {{{")
        mgr = OwnerManager(paths)
        assert mgr.has_owner is False
