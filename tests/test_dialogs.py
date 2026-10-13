"""Tests for dialogs.py: a dialog window holding Houdini's main thread is noticed.

A Python menu script or callback that raises, in a GUI session, opens
Houdini's "Error running Python ..." window, and nothing hdefereval queues
runs until someone closes it: every next command waited out its deadline and
was told "Houdini is still working on it", and a queued one ran when the
window was closed, long after its reply had reported a failure. The window is
not a Qt modal (activeModalWidget() is None) and shows no text Qt can read:
it is a top-level QWidget titled "Houdini". A main-thread timer notes it
(Qt timers keep firing while it is up); the dispatcher and health read the
time it was first seen.

hou and Qt are mocked here; the window was checked live on Houdini 22.0.429.
"""

from __future__ import annotations

# Built-in
import importlib
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-party
import pytest


class _FakeHwebserver(MagicMock):
    """hwebserver whose apiFunction decorator returns the function unchanged."""

    @staticmethod
    def apiFunction(namespace=""):
        return lambda func: func


sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.dialogs as dialogs  # noqa: E402


def _widget(title, visible=True):
    widget = MagicMock()
    widget.isVisible.return_value = visible
    widget.windowTitle.return_value = title
    return widget


@pytest.fixture
def qt(monkeypatch):
    shown = [_widget("scene.hip - Houdini FX 22.0.429")]
    widgets = SimpleNamespace(QApplication=SimpleNamespace(topLevelWidgets=lambda: shown))
    monkeypatch.setitem(sys.modules, "PySide6", SimpleNamespace(QtWidgets=widgets))
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", widgets)
    monkeypatch.setattr(dialogs, "_open_since", None)
    monkeypatch.setattr(dialogs, "_seen_at", 0.0)
    return shown


def test_the_main_window_is_not_a_dialog(qt):
    dialogs._tick()
    assert dialogs.open_for() is None


def test_a_window_titled_houdini_is_noted_until_it_closes(qt):
    window = _widget("Houdini")
    qt.append(window)
    dialogs._tick()
    first = dialogs._open_since
    dialogs._tick()
    assert dialogs._open_since == first  # counted from when it was first seen
    assert dialogs.open_for() >= 0
    window.isVisible.return_value = False
    dialogs._tick()
    assert dialogs.open_for() is None


def test_a_window_not_seen_for_two_ticks_is_not_reported(qt, monkeypatch):
    """Closed, and the commands behind it cook before the next tick: no refusal."""
    qt.append(_widget("Houdini"))
    dialogs._tick()
    assert dialogs.open_for() is not None
    monkeypatch.setattr(dialogs, "_seen_at", dialogs.time.monotonic() - 2)
    assert dialogs.open_for() is None


def test_pyside2_is_used_where_there_is_no_pyside6(qt, monkeypatch):
    """Houdini 20.5 ships PySide2 only."""
    qt.append(_widget("Houdini"))
    monkeypatch.setitem(sys.modules, "PySide2", sys.modules["PySide6"])
    monkeypatch.setitem(sys.modules, "PySide2.QtWidgets", sys.modules["PySide6.QtWidgets"])
    monkeypatch.setitem(sys.modules, "PySide6", None)
    dialogs._tick()
    assert dialogs.open_for() is not None


def test_the_message_says_whether_the_command_was_queued():
    assert "was not queued" in dialogs.message(3)
    assert "waits on it" in dialogs.message(3, queued=True)
    assert "command" not in dialogs.message(3, queued=None)


@pytest.fixture
def health(monkeypatch):
    monkeypatch.setitem(sys.modules, "hwebserver", _FakeHwebserver())
    import fxhoudinimcp_server.hwebserver_app as app

    importlib.reload(app)  # a bare MagicMock hwebserver would make health a mock
    return app.health


def test_health_names_an_open_window(health, monkeypatch):
    monkeypatch.setattr(dialogs, "_open_since", dialogs.time.monotonic() - 5)
    monkeypatch.setattr(dialogs, "_seen_at", dialogs.time.monotonic())
    assert "dialog window" in health(None)["dialog"]


def test_health_says_nothing_without_one(health, monkeypatch):
    monkeypatch.setattr(dialogs, "_open_since", None)
    assert "dialog" not in health(None)
