"""get_help_page reads a long page on, by offset or by section.

A page came back as its first 20,000 characters and nothing else:
nodes/sop/pyrosolver is 50,925, it stopped in Fields, and Shape, Wind and
Buoyancy could not be read at all. A node page's title came back empty: its
"= Pyro Solver =" is the seventh line, after #type, #context, #internal,
#icon and #since. hou is mocked here; the live check ran on Houdini 22.0.466.
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
import fxhoudinimcp_server.handlers.help_handlers as helps  # noqa: E402

_PAGE = (
    "#type:     node\n#context:  sop\n#internal: pyrosolver\n#icon:     DOP/pyrosolver\n#since: 18.0\n\n"
    "= Pyro Solver =\n\n== Overview ==\n"
    + "overview line\n" * 1000
    + "== Shape ==\n~~ Buoyancy ~~\n"
    + "buoyancy line\n" * 600
    + "~~ Wind ~~\nWind Speed:\n"
    + "wind line\n" * 600
    + "== Sourcing == (sourcing)\nend\n"
)


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(helps, "_require_help", lambda: None)
    monkeypatch.setattr(helps, "_available_scopes", lambda: ["nodes"])
    monkeypatch.setattr(helps, "_load_scope", lambda scope: {"sop/pyrosolver": (_PAGE, "")})


def test_title_of_a_node_page(page):
    assert helps.get_help_page("nodes/sop/pyrosolver")["title"] == "Pyro Solver"


def test_long_page_reads_on_by_offset(page):
    texts = []
    reply = helps.get_help_page("nodes/sop/pyrosolver")
    assert reply["truncated"] and "offset" not in reply
    texts.append(reply["text"])
    while "next_offset" in reply:
        reply = helps.get_help_page("nodes/sop/pyrosolver", offset=reply["next_offset"])
        texts.append(reply["text"])
    assert "".join(texts) == _PAGE
    assert not reply["truncated"]
    assert all(text.endswith("\n") for text in texts)


def test_sections_name_tabs_and_folders(page):
    sections = helps.get_help_page("nodes/sop/pyrosolver")["sections"]
    assert [(s["title"], s["level"]) for s in sections] == [
        ("Overview", 1),
        ("Shape", 1),
        ("Buoyancy", 2),
        ("Wind", 2),
        ("Sourcing", 1),
    ]
    wind = helps.get_help_page("nodes/sop/pyrosolver", section="wind")
    assert wind["text"].startswith("~~ Wind ~~\nWind Speed:")
    assert wind["offset"] == _PAGE.index("~~ Wind ~~")


def test_unknown_section_lists_the_sections(page):
    with pytest.raises(ValueError, match="Buoyancy"):
        helps.get_help_page("nodes/sop/pyrosolver", section="Lookdev")


def test_offset_past_the_end_is_refused(page):
    with pytest.raises(ValueError, match="outside"):
        helps.get_help_page("nodes/sop/pyrosolver", offset=len(_PAGE))


def test_short_page_has_no_sections(monkeypatch):
    monkeypatch.setattr(helps, "_require_help", lambda: None)
    monkeypatch.setattr(helps, "_available_scopes", lambda: ["expressions"])
    monkeypatch.setattr(
        helps, "_load_scope", lambda scope: {"ch": ("= ch =\n\n== Usage ==\nch()\n", "")}
    )
    reply = helps.get_help_page("expressions/ch")
    assert reply["title"] == "ch" and not reply["truncated"]
    assert "sections" not in reply and "next_offset" not in reply
