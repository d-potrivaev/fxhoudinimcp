"""Knowing that Houdini shows a dialog window and waits for someone to click.

A Python menu script or callback that raises, in a graphical session, opens
Houdini's "Error running Python ..." window. While it is open the main thread
runs nothing hdefereval queues: in a lesson run every next command waited out
its 120 s deadline and the reply said "Houdini is still working on it", and a
queued connect_nodes_batch was applied when the window was closed by hand,
long after its reply had reported a failure (22.0.429).

The window is not a Qt modal -- ``QApplication.activeModalWidget()`` is None
and ``isModal()`` False: Houdini draws it in a QOpenGLWidget inside a
top-level QWidget titled "Houdini", with no text Qt can read. Measured: no
other visible top-level widget has that title (the main window is
"<hip> - Houdini ..."), and Qt timers keep firing while the window is up. So
a timer on the main thread notes when one is shown, and the dispatcher, on
its own thread, reads a float.
"""

from __future__ import annotations

# Built-in
import contextlib
import time

# Third-party
import hou

# The title Houdini gives its own message and error windows.
_TITLE = "Houdini"
_INTERVAL_MS = 500

# time.monotonic() when the window was first seen, None while there is none.
_open_since: float | None = None
_timer = None


def _tick() -> None:
    global _open_since
    shown = False
    with contextlib.suppress(Exception):
        from PySide6 import QtWidgets

        shown = any(
            widget.isVisible() and widget.windowTitle() == _TITLE
            for widget in QtWidgets.QApplication.topLevelWidgets()
        )
    if not shown:
        _open_since = None
    elif _open_since is None:
        _open_since = time.monotonic()


def watch() -> None:
    """Start noting Houdini's dialog windows; call on the main thread of a UI session."""
    global _timer
    if _timer is not None or not hou.isUIAvailable():
        return
    with contextlib.suppress(Exception):
        from PySide6 import QtCore

        timer = QtCore.QTimer()
        timer.setInterval(_INTERVAL_MS)
        timer.timeout.connect(_tick)
        timer.start()
        _timer = timer


def open_for() -> float | None:
    """Seconds a Houdini dialog window has been open, or None when there is none."""
    since = _open_since
    return None if since is None else time.monotonic() - since


def message(seconds: float, queued: bool = False) -> str:
    """What to tell the caller while a dialog window holds Houdini's main thread.

    *queued*: the command already waits behind the window (it timed out
    there) and runs when the window is closed; otherwise it was not sent.
    """
    fate = (
        "this command is queued behind it and runs when the window is closed"
        if queued
        else "so this command was not queued (a queued one would run later, unseen)"
    )
    return (
        f"Houdini shows a dialog window (titled 'Houdini', open for {seconds:.0f} s) and "
        "waits for someone to click it: most likely an error message from a Python menu "
        f"script or callback. Nothing runs until it is closed; {fate}. Ask the user to "
        "read and close the window, then retry."
    )
