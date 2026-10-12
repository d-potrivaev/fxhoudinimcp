"""set_playback_range widens the global frame range instead of being clamped.

Houdini clamps a playback range to the global one without a word: 1-1200
asked of a 1-240 scene answered start 1, end 240, "playback_range_set", and
the caller believed 1200 frames would play.

hou is mocked here; the handler runs against a fake playbar.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.animation_handlers as animation  # noqa: E402

hou = animation.hou


class _Playbar:
    """A playbar that clamps the playback range to the global one, as Houdini does."""

    def __init__(self, start, end):
        self.global_range = (float(start), float(end))
        self.playback = self.global_range

    def frameRange(self):
        return self.global_range

    def setFrameRange(self, start, end):
        self.global_range = (float(start), float(end))

    def playbackRange(self):
        return self.playback

    def setPlaybackRange(self, start, end):
        low, high = self.global_range
        self.playback = (max(float(start), low), min(float(end), high))


@pytest.fixture
def playbar(monkeypatch):
    fake = _Playbar(1, 240)
    monkeypatch.setattr(hou, "playbar", fake)
    return fake


class TestSetPlaybackRange:
    def test_a_longer_range_widens_the_global_one(self, playbar):
        result = animation._set_playback_range(1, 1200)
        assert (result["start"], result["end"]) == (1.0, 1200.0)
        assert playbar.global_range == (1.0, 1200.0)
        assert result["frame_range_widened"] == {"from": [1.0, 240.0], "to": [1.0, 1200.0]}

    def test_an_earlier_start_widens_it_downwards(self, playbar):
        result = animation._set_playback_range(-10, 100)
        assert (result["start"], result["end"]) == (-10.0, 100.0)
        assert result["frame_range_widened"]["to"] == [-10.0, 240.0]

    def test_a_range_inside_leaves_the_global_one_alone(self, playbar):
        result = animation._set_playback_range(10, 20)
        assert (result["start"], result["end"]) == (10.0, 20.0)
        assert playbar.global_range == (1.0, 240.0)
        assert "frame_range_widened" not in result
