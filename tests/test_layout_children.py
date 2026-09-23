"""Tests for layout_children with auto-layout disabled.

With FXHOUDINIMCP_AUTO_LAYOUT=0 the handler returned its "skipped" reply before
it looked at parent_path, so a path that does not exist answered exactly like a
real network: success False, no message, nothing naming the path. The live
path-validation suite reported it as "rejected a bad parent_path without naming
it". The path is now resolved first, and the skipped reply says what it did.

hou is mocked here; the live path was checked on Houdini 22.0.429.
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
import fxhoudinimcp_server.handlers.node_handlers as nodes  # noqa: E402

GONE = "/obj/definitely_not_a_node_12345"


@pytest.fixture
def network(monkeypatch):
    parent = MagicMock()
    parent.children.return_value = [MagicMock(), MagicMock()]
    monkeypatch.setattr(nodes.hou, "node", lambda path: parent if path == "/obj/geo1" else None)
    return parent


class TestLayoutChildrenWithLayoutDisabled:
    def test_a_missing_network_is_named_not_skipped(self, monkeypatch, network):
        monkeypatch.setattr(nodes, "auto_layout_enabled", lambda: False)
        with pytest.raises(ValueError, match=GONE):
            nodes.layout_children(GONE)

    def test_a_real_network_is_skipped_and_says_so(self, monkeypatch, network):
        monkeypatch.setattr(nodes, "auto_layout_enabled", lambda: False)
        result = nodes.layout_children("/obj/geo1")
        assert result["success"] is False
        assert result["skipped"] is True
        assert result["parent_path"] == "/obj/geo1"
        assert "FXHOUDINIMCP_AUTO_LAYOUT=0" in result["message"]
        assert "/obj/geo1" in result["message"]
        network.layoutChildren.assert_not_called()

    def test_layout_enabled_still_lays_the_network_out(self, monkeypatch, network):
        monkeypatch.setattr(nodes, "auto_layout_enabled", lambda: True)
        result = nodes.layout_children("/obj/geo1")
        assert result == {"success": True, "parent_path": "/obj/geo1", "laid_out_count": 2}
        network.layoutChildren.assert_called_once_with()

    def test_a_missing_network_is_named_with_layout_enabled_too(self, monkeypatch, network):
        monkeypatch.setattr(nodes, "auto_layout_enabled", lambda: True)
        with pytest.raises(ValueError, match=GONE):
            nodes.layout_children(GONE)
