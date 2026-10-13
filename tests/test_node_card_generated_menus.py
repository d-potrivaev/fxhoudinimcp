"""get_node_card showed a script-generated menu as a Menu with no items.

`filemerge::2.0` promotes `loadtype` from an inner `file1`, and its items come
from the script `opmenu -l -a file1 loadtype`. The type's template answers
menuItems() with an empty tuple, so the card carried `"type": "Menu"` and no
`menu` key, and a session took its tokens off the `file` SOP's card instead.
A live parm runs the script. The card already makes a throwaway probe for the
connectors, so the same probe now answers the menu: `menu`, `menu_labels`,
`menu_source: "generator"` and the script in `menu_generator`.

hou is mocked here; the live check ran on Houdini 22.0.429.
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
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402

hou = graph.hou

LOADTYPE_ITEMS = ("full", "infobbox", "info", "points", "delayed", "packedseq", "packedgeo")
LOADTYPE_LABELS = (
    "All Geometry",
    "Bounding Box",
    "Info",
    "Point Cloud",
    "Packed Disk Primitive",
    "Packed Disk Sequence",
    "Packed Geometry",
)
GENERATOR = "opmenu -l -a file1 loadtype"


def _parm(name, items=(), labels=(), template_items=(), generator="", menu_type=None):
    parm = MagicMock()
    menu_type = hou.parmTemplateType.Menu if menu_type is None else menu_type
    parm.name.return_value = name
    parm.menuItems.return_value = tuple(items)
    parm.menuLabels.return_value = tuple(labels)
    template = MagicMock()
    template.menuItems.return_value = tuple(template_items)
    template.itemGeneratorScript.return_value = generator
    template.type.return_value = menu_type
    parm.parmTemplate.return_value = template
    return parm


def _template(name, items=(), label=None, labels=None):
    template = MagicMock()
    template.name.return_value = name
    template.label.return_value = label or name.title()
    template.type.return_value.name.return_value = "Menu"
    template.numComponents.return_value = 1
    template.isHidden.return_value = False
    template.defaultValue.return_value = (0,)
    template.menuItems.return_value = tuple(items)
    template.menuLabels.return_value = tuple(items if labels is None else labels)
    return template


def _probe(parms):
    probe = MagicMock()
    probe.parms.return_value = list(parms)
    probe.inputNames.return_value = ["input1"]
    probe.inputLabels.return_value = ["Input 1"]
    probe.inputDataTypes.return_value = []
    probe.outputNames.return_value = ["output1"]
    probe.outputLabels.return_value = ["Output 1"]
    return probe


class TestGeneratedMenusOfAProbe:
    def test_a_script_generated_menu_is_read_off_the_live_parm(self):
        probe = _probe(
            [
                _parm("loadtype", LOADTYPE_ITEMS, LOADTYPE_LABELS, generator=GENERATOR),
                _parm("static", template_items=("a", "b")),
                _parm("plain"),
            ]
        )
        generated = graph._generated_menus_of(probe)
        assert set(generated) == {"loadtype"}
        assert generated["loadtype"]["items"] == list(LOADTYPE_ITEMS)
        assert generated["loadtype"]["labels"][0] == "All Geometry"
        assert generated["loadtype"]["generator"] == GENERATOR

    def test_a_static_menu_is_left_to_the_template(self):
        probe = _probe([_parm("group", template_items=("a",), generator="x")])
        assert graph._generated_menus_of(probe) == {}

    def test_a_suggestion_menu_is_left_out(self):
        # attribwrangle's snippet (StringReplace) and group pickers
        # (StringToggle): their items are suggestions, not tokens.
        snippet = _parm(
            "snippet", ("// code",), generator="x", menu_type=hou.parmTemplateType.String
        )
        snippet.parmTemplate.return_value.menuType.return_value = "replace"
        assert graph._generated_menus_of(_probe([snippet])) == {}

    def test_a_generator_that_yields_nothing_still_names_its_script(self):
        probe = _probe([_parm("loadtype", generator=GENERATOR)])
        assert graph._generated_menus_of(probe) == {"loadtype": {"generator": GENERATOR}}

    def test_a_menu_script_that_fails_on_the_probe_is_named(self, monkeypatch):
        # Run by menus.py, not menuItems(): a Python one that raises opened a
        # modal window in a GUI session. On the unwired probe it is named.
        def fails(parm):
            raise graph.MenuScriptError(
                "Menu script of /obj/n/attrib raised IndexError: tuple index out of range\n  tail"
            )

        monkeypatch.setattr(graph, "items_and_labels", fails)
        probe = _probe([_parm("attrib", generator="return kwargs['node'].inputs()[0]")])
        assert graph._generated_menus_of(probe) == {
            "attrib": {
                "generator": "return kwargs['node'].inputs()[0]",
                "script_error": "Menu script of /obj/n/attrib raised IndexError: tuple index out of range",
            }
        }

    def test_one_failing_parm_does_not_lose_the_others(self):
        broken = _parm("broken", generator="x")
        broken.menuItems.side_effect = RuntimeError("script error")
        probe = _probe([broken, _parm("loadtype", LOADTYPE_ITEMS, generator=GENERATOR)])
        assert set(graph._generated_menus_of(probe)) == {"loadtype"}


class TestTheCardReadsGeneratedMenus:
    @pytest.fixture(autouse=True)
    def _fresh(self, monkeypatch):
        monkeypatch.setattr(graph, "_CONNECTOR_CACHE", {})
        monkeypatch.setattr(graph, "_definition_stamp", lambda node_type: None)
        monkeypatch.setattr(graph, "_container_for", lambda category: "geo")
        monkeypatch.setattr(graph, "_help_text", lambda resolved, context: None)

    def _card(self, monkeypatch, templates, probe, **kwargs):
        root = MagicMock()
        scratch = MagicMock()
        root.createNode.return_value = scratch
        scratch.createNode.return_value = probe
        monkeypatch.setattr(hou, "node", lambda path: root)

        resolved = MagicMock()
        resolved.name.return_value = "filemerge::2.0"
        resolved.description.return_value = "File Merge"
        resolved.minNumInputs.return_value = 0
        resolved.maxNumInputs.return_value = 0
        resolved.maxNumOutputs.return_value = 1
        resolved.parmTemplateGroup.return_value.entriesWithoutFolders.return_value = templates
        resolved.parmTemplateGroup.return_value.entries.return_value = []
        monkeypatch.setattr(hou, "nodeTypeCategories", lambda: {"Sop": MagicMock()})
        monkeypatch.setattr(graph, "_resolve_node_type", lambda category, name: resolved)
        card = graph.get_node_card("filemerge", "Sop", **kwargs)
        return card, root

    def test_the_card_lists_the_generated_items_with_labels_and_source(self, monkeypatch):
        probe = _probe([_parm("loadtype", LOADTYPE_ITEMS, LOADTYPE_LABELS, generator=GENERATOR)])
        card, _ = self._card(monkeypatch, [_template("loadtype")], probe, parm_filter="loadtype")
        (entry,) = card["parms"]
        assert entry["menu"] == list(LOADTYPE_ITEMS)
        assert entry["menu_labels"] == list(LOADTYPE_LABELS)
        assert entry["menu_source"] == "generator"
        assert entry["menu_generator"] == GENERATOR
        assert "note" not in entry
        assert card["connectors_probed"] is True

    def test_a_static_menu_keeps_the_template_and_says_so(self, monkeypatch):
        probe = _probe([])
        card, _ = self._card(monkeypatch, [_template("mode", items=("a", "b"))], probe)
        (entry,) = card["parms"]
        assert entry["menu"] == ["a", "b"]
        assert entry["menu_source"] == "template"
        assert "menu_generator" not in entry

    def test_a_static_menu_of_numbers_carries_its_labels(self, monkeypatch):
        # pyrosource's Mode came as "0"/"1"/"2" and nothing else.
        labels = ("Surface Scatter", "Keep Input", "Volume Scatter")
        template = _template("mode", items=("0", "1", "2"), labels=labels)
        card, _ = self._card(monkeypatch, [template], _probe([]))
        (entry,) = card["parms"]
        assert entry["menu"] == ["0", "1", "2"]
        assert entry["menu_labels"] == list(labels)
        assert entry["menu_source"] == "template"

    def test_labels_that_repeat_the_tokens_are_left_out(self, monkeypatch):
        card, _ = self._card(monkeypatch, [_template("mode", items=("a", "b"))], _probe([]))
        (entry,) = card["parms"]
        assert "menu_labels" not in entry

    def test_an_empty_generated_menu_is_not_shown_as_no_menu(self, monkeypatch):
        probe = _probe([_parm("loadtype", generator=GENERATOR)])
        card, _ = self._card(monkeypatch, [_template("loadtype")], probe)
        (entry,) = card["parms"]
        assert "menu" not in entry
        assert entry["menu_generator"] == GENERATOR
        assert "menu_generator" in entry["note"]

    def test_a_menu_script_that_failed_on_the_probe_is_named_on_the_card(self, monkeypatch):
        def fails(parm):
            raise graph.MenuScriptError(
                "Menu script of /obj/n/loadtype raised IndexError: x\n  tail"
            )

        monkeypatch.setattr(graph, "items_and_labels", fails)
        probe = _probe([_parm("loadtype", generator=GENERATOR)])
        card, _ = self._card(monkeypatch, [_template("loadtype")], probe)
        (entry,) = card["parms"]
        assert entry["menu_script_error"] == "Menu script of /obj/n/loadtype raised IndexError: x"
        assert "menu_generator" in entry["note"]

    def test_a_second_card_reads_the_menus_from_the_cache(self, monkeypatch):
        probe = _probe([_parm("loadtype", LOADTYPE_ITEMS, generator=GENERATOR)])
        _, first_root = self._card(monkeypatch, [_template("loadtype")], probe)
        card, second_root = self._card(monkeypatch, [_template("loadtype")], probe)
        first_root.createNode.assert_called_once()
        second_root.createNode.assert_not_called()
        assert card["parms"][0]["menu"] == list(LOADTYPE_ITEMS)
        assert card["parms"][0]["menu_source"] == "generator"


class _FolderSetTemplate:
    """Stands in for hou.FolderSetParmTemplate, so isinstance() can find it."""

    def __init__(self, folder_type, names):
        self._type, self._names = folder_type, names

    def folderType(self):
        return self._type

    def folderNames(self):
        return tuple(self._names)


class _CardHarness:
    """TestTheCardReadsGeneratedMenus' probe and card, for the classes below."""

    _fresh = TestTheCardReadsGeneratedMenus._fresh
    _card = TestTheCardReadsGeneratedMenus._card


def _folder_set(name, folder_type, names):
    parm = MagicMock()
    parm.name.return_value = name
    parm.parmTemplate.return_value = _FolderSetTemplate(folder_type, names)
    return parm


class TestRadioFoldersAreParametersOnTheCard(_CardHarness):
    """An Add SOP's card had no `switcher1`, the parm that picks By Pattern or By Group.

    The template walk skips folders, and the radio set's parameter went with
    them: 12 parms on the card, 16 on a live Add. Which folder is picked
    decides the result (`attrname=id` made 0 primitives under By Pattern and
    126 under By Group). Radio sets are read off the probe under their live
    name and listed as a FolderSet parm whose menu is the folders; tab
    folders only choose what the pane shows and stay out.
    """

    @pytest.fixture(autouse=True)
    def _types(self, monkeypatch):
        monkeypatch.setattr(hou, "FolderSetParmTemplate", _FolderSetTemplate, raising=False)
        monkeypatch.setattr(
            hou,
            "folderType",
            MagicMock(RadioButtons="radio", Tabs="tabs"),
            raising=False,
        )

    def _add_probe(self):
        return _probe(
            [
                _folder_set("switcher1", "radio", ["By Pattern", "By Group"]),
                _folder_set("stdswitcher1", "tabs", ["Points", "Polygons"]),
                _parm("attrname"),
            ]
        )

    def test_a_radio_set_is_read_off_the_probe_and_tabs_are_not(self):
        assert graph._radio_folder_sets_of(self._add_probe()) == {
            "switcher1": {
                "folder_set": "RadioButtons",
                "items": ["0", "1"],
                "labels": ["By Pattern", "By Group"],
            }
        }

    def test_the_card_lists_the_set_as_a_menu_of_its_folders(self, monkeypatch):
        card, _ = self._card(
            monkeypatch, [_template("attrname", label="Attribute Name")], self._add_probe()
        )
        entry = next(p for p in card["parms"] if p["name"] == "switcher1")
        assert entry["type"] == "FolderSet"
        assert entry["menu"] == ["0", "1"]
        assert entry["menu_labels"] == ["By Pattern", "By Group"]
        assert entry["menu_source"] == "folder_set"
        assert "stdswitcher1" not in [p["name"] for p in card["parms"]]
        assert card["parm_count"] == card["parms_matched"] == 2

    def test_a_filter_finds_it_by_a_folder_s_label(self, monkeypatch):
        card, _ = self._card(
            monkeypatch,
            [_template("attrname", label="Attribute Name")],
            self._add_probe(),
            parm_filter="group",
        )
        assert [p["name"] for p in card["parms"]] == ["switcher1"]


class TestTheCardShowsADefaultExpression(_CardHarness):
    """timeshift's card said `frame: default [0.0]`; a new Time Shift has frame = $F.

    Only a build's `expressions_removed` told otherwise. The template's
    defaultExpression() is now on the card as `default_expression`.
    """

    def _entry(self, monkeypatch, expressions):
        frame = _template("frame")
        frame.defaultValue.return_value = (0.0,)
        frame.defaultExpression.return_value = expressions
        card, _ = self._card(monkeypatch, [frame], _probe([]))
        return card["parms"][0]

    def test_an_expression_default_is_named(self, monkeypatch):
        entry = self._entry(monkeypatch, ("$F",))
        assert entry["default"] == [0.0]
        assert entry["default_expression"] == ["$F"]

    def test_a_plain_default_has_none(self, monkeypatch):
        assert "default_expression" not in self._entry(monkeypatch, ("",))

    def test_a_toggle_s_one_string_is_not_split_into_letters(self, monkeypatch):
        # Toggle and Menu templates return a str, not a tuple.
        entry = self._entry(monkeypatch, 'ch("../enable")')
        assert entry["default_expression"] == ['ch("../enable")']

    def test_a_toggle_s_on_or_off_is_its_value_not_an_expression(self, monkeypatch):
        assert "default_expression" not in self._entry(monkeypatch, "off")
        assert "default_expression" not in self._entry(monkeypatch, "on")

    def test_the_component_holding_the_expression_is_kept_in_place(self, monkeypatch):
        entry = self._entry(monkeypatch, ("", "$F", ""))
        assert entry["default_expression"] == ["", "$F", ""]


def _string_template(menu_type=None, tags=None):
    template = MagicMock()
    template.type.return_value = hou.parmTemplateType.String
    template.menuType.return_value = hou.menuType.Normal if menu_type is None else menu_type
    template.tags.return_value = dict(tags or {})
    return template


class TestWhichMenusAreStrict:
    """Houdini refuses an off-menu value only on a Menu parm (measured on 22.0.429).

    A String parm with a normal menu takes any text. Its tokens are still
    checked (a typo there writes a value nothing reads), except on a code
    field, whose menu only inserts snippets: a popforce's VEXpression was
    refused by build_network as "not a menu item" though Houdini takes it.
    """

    def test_a_menu_parm_is_strict(self):
        template = MagicMock()
        template.type.return_value = hou.parmTemplateType.Menu
        assert graph._is_strict_menu(template)

    def test_a_string_choice_menu_is_still_checked(self):
        assert graph._is_strict_menu(_string_template())

    def test_a_code_field_with_a_snippet_menu_is_free_text(self):
        vexpression = _string_template(tags={"editor": "1", "editorlang": "vex"})
        assert not graph._is_strict_menu(vexpression)

    def test_a_replace_menu_is_free_text(self):
        assert not graph._is_strict_menu(_string_template(menu_type="replace"))

    def test_unreadable_tags_keep_the_menu_strict(self):
        template = _string_template()
        template.tags.side_effect = RuntimeError("no tags")
        assert graph._is_strict_menu(template)


class TestBuildNetworkTakesCodeInASnippetField:
    def _network(self, monkeypatch):
        code = _parm("localnoiseexpression", ("amp = 1;", "offset = @P;"), generator="x")
        code.parmTemplate.return_value = _string_template(tags={"editor": "1"})
        mode = _parm("mode", ("velocity", "force"))
        probe = _probe([code, mode])
        probe.parmTuples.return_value = []
        for parm in (code, mode):
            parm.expression.return_value = ""
        parent = MagicMock()
        parent.path.return_value = "/obj/dopnet1"
        parent.children.return_value = []
        parent.displayNode.return_value = None
        parent.renderNode.return_value = None
        parent.childTypeCategory.return_value.name.return_value = "Dop"
        parent.createNode.return_value = probe
        node_type = MagicMock()
        node_type.name.return_value = "popforce"
        node_type.maxNumInputs.return_value = 4
        node_type.definition.return_value = None
        monkeypatch.setattr(graph, "_PARM_PROBE_CACHE", {})
        monkeypatch.setattr(hou, "node", lambda path: parent if path == parent.path() else None)
        monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: node_type)
        monkeypatch.setattr(graph, "_instance_patterns", lambda t: [])

    def _dry(self, parms):
        return graph.build_network(
            "/obj/dopnet1", [{"type": "popforce", "name": "pf", "parms": parms}], dry_run=True
        )

    def test_the_vexpression_validates(self, monkeypatch):
        self._network(monkeypatch)
        result = self._dry({"localnoiseexpression": "offset.x = @id;"})
        assert result["valid"] is True, result

    def test_a_typo_in_a_menu_token_is_still_caught(self, monkeypatch):
        self._network(monkeypatch)
        result = self._dry({"mode": "velocty"})
        assert result["valid"] is False
        assert "'velocty' is not a menu item" in result["errors"][0]


def _typed_card(monkeypatch, context, type_name, templates, probe, definition=None, **kwargs):
    """A card for *type_name* in *context*, its probes all answered by *probe*."""
    root = MagicMock()
    scratch = MagicMock()
    root.createNode.return_value = scratch
    scratch.createNode.return_value = probe
    monkeypatch.setattr(hou, "node", lambda path: root)
    resolved = MagicMock()
    resolved.name.return_value = type_name
    resolved.minNumInputs.return_value = 0
    resolved.maxNumInputs.return_value = 1
    resolved.maxNumOutputs.return_value = 1
    resolved.parmTemplateGroup.return_value.entriesWithoutFolders.return_value = templates
    resolved.parmTemplateGroup.return_value.entries.return_value = []
    resolved.definition.return_value = definition
    monkeypatch.setattr(hou, "nodeTypeCategories", lambda: {context: MagicMock()})
    monkeypatch.setattr(graph, "_resolve_node_type", lambda category, name: resolved)
    return graph.get_node_card(type_name, context, **kwargs), root, scratch


def _definition(sections):
    definition = MagicMock()
    definition.sections.return_value = sections
    return definition


class TestTheCardListsParmsAddedOnCreate:
    """rendergeometrysettings' card answered `parm_count: 0` for "Render Points As".

    The type has 16 parm templates and a new node 180: the asset's OnCreated
    script (loputils.addRendererParmFolders) adds the rest, and the card's
    probe runs without creation scripts. A second probe, with them, is made
    for a type that has an OnCreated section; what it adds is on the card
    with `added_on_create`, counted in `parms_added_on_create`.
    """

    POINT_STYLE = "xn__primvarskarmaobjectpoint_style_zpbfg"

    @pytest.fixture(autouse=True)
    def _fresh(self, monkeypatch):
        monkeypatch.setattr(graph, "_CONNECTOR_CACHE", {})
        monkeypatch.setattr(graph, "_ON_CREATED_CACHE", {})
        monkeypatch.setattr(graph, "_definition_stamp", lambda node_type: None)
        monkeypatch.setattr(graph, "_container_for", lambda category: "lopnet")
        monkeypatch.setattr(graph, "_help_text", lambda resolved, context: None)
        monkeypatch.setattr(graph, "_factory_type", lambda node_type: True)

    def _probe(self):
        probe = _probe([])
        probe.parmTemplateGroup.return_value.entriesWithoutFolders.return_value = [
            _template("primpattern"),
            _template(self.POINT_STYLE, label="Render Points As"),
        ]
        return probe

    def _card(self, monkeypatch, sections, **kwargs):
        return _typed_card(
            monkeypatch,
            "Lop",
            "rendergeometrysettings",
            [_template("primpattern")],
            self._probe(),
            definition=_definition(sections),
            **kwargs,
        )

    def test_the_parms_a_creation_script_adds_are_on_the_card(self, monkeypatch):
        card, _, scratch = self._card(
            monkeypatch, {"OnCreated": object()}, parm_filter="point_style"
        )
        (entry,) = card["parms"]
        assert entry["name"] == self.POINT_STYLE
        assert entry["label"] == "Render Points As"
        assert entry["added_on_create"] is True
        assert card["parm_count"] == 1
        assert card["parms_added_on_create"] == 1
        # The connector probe skips creation scripts; this one runs them.
        scratch.createNode.assert_any_call("rendergeometrysettings")

    def test_the_type_s_own_parms_are_not_flagged(self, monkeypatch):
        card, _, _ = self._card(monkeypatch, {"OnCreated": object()})
        flagged = {entry["name"]: "added_on_create" in entry for entry in card["parms"]}
        assert flagged == {"primpattern": False, self.POINT_STYLE: True}

    def test_a_type_without_oncreated_gets_no_second_probe(self, monkeypatch):
        card, root, _ = self._card(monkeypatch, {"DialogScript": object()})
        assert [entry["name"] for entry in card["parms"]] == ["primpattern"]
        assert "parms_added_on_create" not in card
        root.createNode.assert_called_once()  # the connector probe alone

    def test_a_second_card_reads_them_from_the_cache(self, monkeypatch):
        self._card(monkeypatch, {"OnCreated": object()})
        card, root, _ = self._card(monkeypatch, {"OnCreated": object()})
        root.createNode.assert_not_called()
        assert card["parms_added_on_create"] == 1

    def test_a_failed_probe_leaves_the_card_to_the_type(self, monkeypatch):
        node_type = MagicMock()
        node_type.definition.return_value = _definition({"OnCreated": object()})
        root = MagicMock()
        scratch = root.createNode.return_value
        scratch.createNode.side_effect = RuntimeError("no license for this type")
        monkeypatch.setattr(hou, "node", lambda path: root)
        assert graph._on_created_templates("Lop", node_type) == []
        scratch.destroy.assert_called_once()

    def test_an_asset_from_outside_hfs_is_not_created(self, monkeypatch):
        # A Labs biome node's OnCreated writes JSON under $HIP/data/biome.
        monkeypatch.setattr(graph, "_factory_type", lambda node_type: False)
        node_type = MagicMock()
        node_type.definition.return_value = _definition({"OnCreated": object()})
        root = MagicMock()
        monkeypatch.setattr(hou, "node", lambda path: root)
        assert graph._on_created_templates("Sop", node_type) == []
        root.createNode.assert_not_called()


class TestTheCardListsEverySignatureOfAVop:
    """A fresh setattrib's `signature` menu offers `default` alone.

    The menu lists what the node can take as wired, so the tokens of the
    other 19 signatures (`f`, `m3`, `v4`) had to be found by wiring probes
    and reading inputDataTypes(). The type's DialogScript names them all;
    the card lists them in `signatures` and as the `signature` menu.
    """

    DIALOG = """
    signature\t"Float Attribute"\tf  { int string string string int int float }
    signature\t"Vector Attribute"\tdefault { }
    signature\t"Matrix3 Attribute"\tm3 { int string string string int int matrix3 }
    """

    @pytest.fixture(autouse=True)
    def _fresh(self, monkeypatch):
        monkeypatch.setattr(graph, "_CONNECTOR_CACHE", {})
        monkeypatch.setattr(graph, "_ON_CREATED_CACHE", {})
        monkeypatch.setattr(graph, "_definition_stamp", lambda node_type: None)
        monkeypatch.setattr(graph, "_container_for", lambda category: "matnet")
        monkeypatch.setattr(graph, "_help_text", lambda resolved, context: None)

    def _dialog(self):
        return _definition({"DialogScript": MagicMock(contents=lambda: self.DIALOG)})

    def test_every_signature_is_read_with_its_token(self):
        node_type = MagicMock()
        node_type.definition.return_value = self._dialog()
        found = graph._vop_signatures(node_type)
        assert [s["name"] for s in found] == ["f", "default", "m3"]
        assert found[0]["label"] == "Float Attribute"
        assert found[0]["input_types"][-1] == "float"
        assert "input_types" not in found[1]

    def test_a_type_without_a_definition_has_none(self):
        node_type = MagicMock()
        node_type.definition.return_value = None
        assert graph._vop_signatures(node_type) == []

    def _signature_card(self, monkeypatch, context):
        signature = _template("signature", items=("default",), labels=("Vector Attribute",))
        card, _, _ = _typed_card(
            monkeypatch, context, "setattrib", [signature], _probe([]), definition=self._dialog()
        )
        return card

    def test_the_signature_menu_is_every_token(self, monkeypatch):
        card = self._signature_card(monkeypatch, "Vop")
        (entry,) = card["parms"]
        assert entry["menu"] == ["f", "default", "m3"]
        assert entry["menu_labels"] == [
            "Float Attribute",
            "Vector Attribute",
            "Matrix3 Attribute",
        ]
        assert entry["menu_source"] == "signatures"
        assert [s["name"] for s in card["signatures"]] == ["f", "default", "m3"]
        assert "signatures_note" in card

    def test_another_context_keeps_the_template_menu(self, monkeypatch):
        card = self._signature_card(monkeypatch, "Sop")
        (entry,) = card["parms"]
        assert entry["menu"] == ["default"]
        assert entry["menu_source"] == "template"
        assert "signatures" not in card
