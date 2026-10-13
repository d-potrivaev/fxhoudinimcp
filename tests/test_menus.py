"""Tests for menus.py: a parameter's menu is read without Houdini's modal error window.

hou.Parm.menuItems() runs the menu's generator script. In a GUI session a
Python one that raises opens a modal "Error running Python menu script in
parameter" window, and the bridge hangs until someone clicks OK: build_network's
type probe read every menu of a fresh, unwired kinefx::characterblendshapes, and
its group menu calls inputGeometry(0).generateGroupMenu(...) on None. menus.py
runs a Python menu script itself, with what Houdini hands it (measured on
22.0.429), and turns its exception into MenuScriptError; HScript and static
menus, which open no such window (measured), still go through menuItems().

hou is mocked here; menus.py was compared with menuItems() over every Python
menu of every node type in hython on 22.0.429 (4084 menus, no difference where
Houdini's script ran clean), and the window checked live in a GUI session.
"""

from __future__ import annotations

# Built-in
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.menus as menus  # noqa: E402

hou = menus.hou
PYTHON, HSCRIPT, BUTTON, STRING = "py", "hs", "button", "string"


def _menu_parm(script, language=PYTHON, indices=(), kind=STRING, items=(), labels=()):
    node = MagicMock()
    node.path.return_value = "/obj/geo1/n"
    parm = MagicMock()
    parm.name.return_value = "group"
    parm.node.return_value = node
    parm.multiParmInstanceIndices.return_value = indices
    template = parm.parmTemplate.return_value
    template.itemGeneratorScript.return_value = script
    template.itemGeneratorScriptLanguage.return_value = language
    template.type.return_value = kind
    parm.menuItems.return_value = items
    parm.menuLabels.return_value = labels
    return parm


@pytest.fixture
def menu_env(monkeypatch):
    monkeypatch.setattr(hou, "scriptLanguage", SimpleNamespace(Python=PYTHON), raising=False)
    monkeypatch.setattr(hou, "parmTemplateType", SimpleNamespace(Button=BUTTON), raising=False)
    pwd = {"node": None}
    monkeypatch.setattr(hou, "pwd", lambda: pwd["node"], raising=False)
    monkeypatch.setattr(hou, "setPwd", lambda node: pwd.update(node=node), raising=False)
    return pwd


class TestMenuScripts:
    def test_an_expression_and_a_function_body_both_list_the_menu(self, menu_env):
        assert menus.items_and_labels(_menu_parm('["a", "A", "b", "B"]')) == (
            ["a", "b"],
            ["A", "B"],
        )
        body = 'r = ["x", "X"]\nreturn r + [kwargs["node"].path(), "N"]'
        assert menus.items_and_labels(_menu_parm(body)) == (["x", "/obj/geo1/n"], ["X", "N"])

    def test_a_raising_script_is_a_menu_script_error_not_a_dialog(self, menu_env):
        # characterblendshapes' group menu on an unwired node (22.0.429).
        parm = _menu_parm("geo = None\nreturn geo.generateGroupMenu(None)")
        with pytest.raises(menus.MenuScriptError, match="AttributeError.*generateGroupMenu"):
            menus.items_and_labels(parm)
        parm.menuItems.assert_not_called()

    def test_pwd_is_the_node_while_it_runs_and_restored_after(self, menu_env):
        parm = _menu_parm('[hou.pwd().path(), "here"]')
        before = object()
        menu_env["node"] = before
        assert menus.items(parm) == ["/obj/geo1/n"]
        assert menu_env["node"] is before

    def test_kwargs_are_strings_outside_a_multiparm_and_ints_inside(self, menu_env):
        script = (
            "r = []\nfor k in sorted(kwargs):\n"
            "    if k.startswith('script'):\n"
            "        r += [k, type(kwargs[k]).__name__ + ':' + str(kwargs[k])]\nreturn r"
        )
        plain = dict(zip(*menus.items_and_labels(_menu_parm(script)), strict=True))
        assert plain == {
            "script_multiparm_index": "str:-1",
            "script_multiparm_nesting": "str:0",
        }
        # m3_1: outermost first -- index 1, index2 3 (measured).
        nested = dict(zip(*menus.items_and_labels(_menu_parm(script, indices=(3, 1))), strict=True))
        assert nested == {
            "script_multiparm_index": "int:1",
            "script_multiparm_index2": "int:3",
            "script_multiparm_nesting": "int:2",
        }

    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            ('["a", "A", "", "", "b", "B"]', (["a"], ["A"])),  # both empty: the end
            ('["", "", "a", "A"]', ([], [])),
            ('["", "None", "a", "A"]', (["", "a"], ["None", "A"])),  # a label: kept
            ('["a", "A", "b"]', ([], [])),  # odd length: no menu at all
            ("[1, 2]", (["1"], ["2"])),
        ],
    )
    def test_the_result_is_read_as_houdini_reads_it(self, menu_env, result, expected):
        assert menus.items_and_labels(_menu_parm(result)) == expected

    @pytest.mark.parametrize(
        "script",
        ["None", "5", '  ["a", "A"]', 'r = ["a", "A"]'],
        ids=["none", "int", "indented-expression", "body-without-return"],
    )
    def test_what_houdini_refuses_is_a_menu_script_error(self, menu_env, script):
        """Each opens Houdini's window (22.0.368); not an empty menu, and not a TypeError."""
        before = object()
        menu_env["node"] = before
        with pytest.raises(menus.MenuScriptError):
            menus.items(_menu_parm(script))
        assert menu_env["node"] is before

    def test_hscript_static_and_button_menus_are_left_to_houdini(self, menu_env):
        for parm in (
            _menu_parm("echo a A", language=HSCRIPT, items=("a",), labels=("A",)),
            _menu_parm("", items=("s",), labels=("S",)),
            _menu_parm('["b", "B"]', kind=BUTTON, items=("x",), labels=("X",)),
        ):
            assert menus.items_and_labels(parm) == (
                list(parm.menuItems.return_value),
                list(parm.menuLabels.return_value),
            )
