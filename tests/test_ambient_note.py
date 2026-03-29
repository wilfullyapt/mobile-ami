"""Unit tests for core/ambient_note.py"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from core.ally.ambient_note import AmbientNote
from core.ally.listener import AmbientUtterance


def _make_utterance(speaker, is_owner, text, seconds_ago=60, duration=1.0):
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return AmbientUtterance(
        speaker=speaker,
        is_owner=is_owner,
        text=text,
        timestamp=ts,
        audio_duration_sec=duration,
    )


def _make_note(utterances=None, unknown_clips=None, index=0):
    now = datetime.now(timezone.utc)
    return AmbientNote(
        chunk_index=index,
        chunk_start=now - timedelta(seconds=180),
        chunk_end=now,
        utterances=utterances or [],
        unknown_clip_paths=unknown_clips or [],
    )


# ---------------------------------------------------------------------------
# formatted_text
# ---------------------------------------------------------------------------

class TestFormattedText:
    def test_formatted_text_marks_owner(self):
        u = _make_utterance("Alice", True, "Hello there", seconds_ago=100)
        note = _make_note([u])
        text = note.formatted_text()
        assert "Alice (owner)" in text
        assert "Hello there" in text

    def test_formatted_text_unknown_speaker(self):
        u = _make_utterance(None, False, "Who are you?", seconds_ago=50)
        note = _make_note([u])
        text = note.formatted_text()
        assert "unknown" in text
        assert "Who are you?" in text

    def test_formatted_text_seconds_ago(self):
        fixed_now = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)
        ts = fixed_now - timedelta(seconds=420)
        u = AmbientUtterance(
            speaker="Bob",
            is_owner=False,
            text="What should I cook?",
            timestamp=ts,
        )
        note = _make_note([u])
        with patch("core.ally.ambient_note.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            text = note.formatted_text()
        assert "420s ago" in text
        assert "Bob" in text
        assert "What should I cook?" in text

    def test_formatted_text_empty_utterances(self):
        note = _make_note([])
        assert note.formatted_text() == ""

    def test_formatted_text_multiple_lines(self):
        u1 = _make_utterance("Mom", True, "Dinner time", seconds_ago=200)
        u2 = _make_utterance(None, False, "Ok", seconds_ago=190)
        note = _make_note([u1, u2])
        lines = note.formatted_text().splitlines()
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_to_dict_roundtrip_via_from_dict(self):
        u = _make_utterance("Alice", True, "Test text", seconds_ago=30)
        original = _make_note([u], unknown_clips=["/tmp/clip.wav"], index=3)
        d = original.to_dict()
        restored = AmbientNote.from_dict(d)

        assert restored.chunk_index == 3
        assert len(restored.utterances) == 1
        assert restored.utterances[0].text == "Test text"
        assert restored.utterances[0].speaker == "Alice"
        assert restored.utterances[0].is_owner is True
        assert restored.unknown_clip_paths == ["/tmp/clip.wav"]

    def test_json_roundtrip(self):
        u = _make_utterance("Jake", False, "Hey", seconds_ago=10)
        original = _make_note([u])
        restored = AmbientNote.from_json(original.to_json())
        assert restored.utterances[0].text == "Hey"
        assert restored.utterances[0].speaker == "Jake"

    def test_from_dict_empty_utterances(self):
        original = _make_note([])
        d = original.to_dict()
        restored = AmbientNote.from_dict(d)
        assert restored.utterances == []
        assert restored.unknown_clip_paths == []
