"""Reading a parameter's menu the way Houdini lists it, without its error dialog.

``hou.Parm.menuItems()`` runs the menu's item generator script. In a graphical
session a PYTHON generator that raises is answered with Houdini's modal "Error
running Python menu script in parameter" window, and Houdini's main thread --
which every command of this bridge runs on -- waits for someone to click OK.
Measured on 22.0.429: ``menuItems()`` itself returned ``[]``, the
window opened right after, and the next command timed out. The trigger was
build_network's type probe reading every menu of a fresh, unwired
``kinefx::characterblendshapes``: its ``group`` menu calls
``inputGeometry(0).generateGroupMenu(...)``, and an empty input is None.

What was measured per route, in a GUI session (as callbacks.py did for buttons):

* no generator script -- a static menu: ``menuItems()`` runs nothing.
* HScript generator that fails -- no window; ``menuItems()`` answers ``[]``.
* Python generator -- the window on an exception. So the script is executed
  here instead, with what Houdini hands it (measured): globals ``hou`` and
  ``kwargs``; kwargs ``node``, ``parm``, ``script_multiparm_index`` and
  ``script_multiparm_nesting`` -- the strings '-1' and '0' outside a
  multiparm, ints inside one (rbdcarfracture's ``type1`` formats the index
  with %d), plus ``script_multiparm_index2`` and up for the outer levels;
  ``hou.pwd()`` is the node. Both forms Houdini accepts are accepted: a bare
  expression (``["a", "A", "b", "B"]``) and a function body ending in
  ``return``. An exception comes back as MenuScriptError.

How Houdini reads the result (measured): it alternates token and label, a
pair with both empty ends the menu (``["a", "A", "", "", "b", "B"]`` is just
``a``; an empty token with a label is kept), an odd-length list gives no
menu at all, entries are made strings. A Button with a generator is not a
menu (``menuItems()`` refuses it without running anything), so it is left to
Houdini. Checked against ``menuItems()`` over every Python menu of every
type in hython (3435 menus of SOP and LOP, 649 of OBJ, DOP, VOP, COP and
TOP): identical wherever Houdini's script ran clean. Where it raised, Houdini answered ``[]`` -- or, now and then, the
items of the menu read before it.
"""

from __future__ import annotations

# Built-in
import builtins
import contextlib
import textwrap
import traceback
from typing import Any

# Third-party
import hou


class MenuScriptError(RuntimeError):
    """A parameter's Python menu script raised; the message carries its traceback tail."""


def generator_script(parm: hou.Parm) -> tuple[str, bool]:
    """The parm's menu generator script and whether it is Python; ("", False) if none."""
    with contextlib.suppress(Exception):
        template = parm.parmTemplate()
        script = template.itemGeneratorScript()
        if isinstance(script, str) and script.strip():
            return script, template.itemGeneratorScriptLanguage() == hou.scriptLanguage.Python
    return "", False


def _menu_kwargs(parm: hou.Parm) -> dict[str, Any]:
    """The kwargs Houdini gives a Python menu script (measured on 22.0.429)."""
    indices: tuple = ()
    with contextlib.suppress(Exception):
        indices = tuple(parm.multiParmInstanceIndices())
    kwargs: dict[str, Any] = {"node": parm.node(), "parm": parm}
    if not indices:
        kwargs.update(script_multiparm_index="-1", script_multiparm_nesting="0")
        return kwargs
    # Outermost first: m3_1 is index 1, index2 3 (as for callbacks).
    kwargs["script_multiparm_index"] = int(indices[-1])
    kwargs["script_multiparm_nesting"] = len(indices)
    for level, number in enumerate(reversed(indices[:-1]), 2):
        kwargs[f"script_multiparm_index{level}"] = int(number)
    return kwargs


def _script_name(parm: hou.Parm) -> str:
    with contextlib.suppress(Exception):
        return f"{parm.node().path()}/{parm.name()}"
    return parm.name()


def run_python_menu(parm: hou.Parm, script: str) -> list[str]:
    """Run *script* as Houdini runs a Python menu script; the flat token/label list."""
    node = parm.node()
    namespace = {"hou": hou, "kwargs": _menu_kwargs(parm), "__builtins__": builtins}
    name = _script_name(parm)
    previous = hou.pwd()
    hou.setPwd(node)
    try:
        try:
            code = compile(script, name, "eval")
        except SyntaxError:
            # A function body: statements, ending in `return`.
            body = "def __fxh_menu__():\n" + textwrap.indent(script, "    ")
            exec(compile(body, name, "exec"), namespace)  # noqa: S102 -- the node's own menu script
            result = namespace["__fxh_menu__"]()
        else:
            result = eval(code, namespace)  # noqa: S307 -- the node's own menu script
        # Houdini answers these with its error window (measured on 22.0.368):
        # None, so a body that never returns or an indented expression
        # wrapped into one, and anything not iterable, such as an int.
        if result is None:
            raise TypeError("Python menu scripts must return a sequence of strings")
        flat = [str(entry) for entry in result]
    except Exception as exc:
        frames = traceback.format_tb(exc.__traceback__.tb_next)[-3:]
        tail = "".join(frames).rstrip()
        raise MenuScriptError(
            f"Menu script of {name} raised {type(exc).__name__}: {exc}\n{tail}"
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            hou.setPwd(previous)
    return flat


def _python_generator(parm: hou.Parm) -> str:
    """The Python script Houdini would run for *parm*'s menu; "" when it runs none."""
    script, is_python = generator_script(parm)
    if not (script and is_python):
        return ""
    with contextlib.suppress(Exception):
        # A Button with a generator is not a menu: menuItems() refuses it
        # without running anything.
        if parm.parmTemplate().type() == hou.parmTemplateType.Button:
            return ""
    return script


def _read(flat: list[str]) -> tuple[list[str], list[str]]:
    if len(flat) % 2:
        return [], []
    tokens: list[str] = []
    labels: list[str] = []
    for token, label in zip(flat[::2], flat[1::2], strict=True):
        if not token and not label:
            break  # the end of the menu: perforce's changelist menu pads with ""
        tokens.append(token)
        labels.append(label)
    return tokens, labels


def items_and_labels(parm: hou.Parm) -> tuple[list[str], list[str]]:
    """The parm's menu tokens and labels; MenuScriptError if its Python script raises."""
    if script := _python_generator(parm):
        return _read(run_python_menu(parm, script))
    return list(parm.menuItems()), list(parm.menuLabels())


def items(parm: hou.Parm) -> list[str]:
    """The parm's menu tokens; MenuScriptError if its Python script raises."""
    if script := _python_generator(parm):
        return _read(run_python_menu(parm, script))[0]
    return list(parm.menuItems())
