"""What reported_outputs lists for a node that writes to disk.

A File Cache SOP carries both `sopoutput` (the path its internal ROP writes)
and `file` (the Explicit-mode path, which sopoutput reads through chs("file")).
In Constructed mode `file` is hidden and never written, yet it was listed with
exists: false beside the cache that was, and read as a failed write.

hou is mocked here; the function is exercised directly.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.outputs as outputs  # noqa: E402

# Taken at import: a test in test_storm_session_fixes.py replaces the module
# attribute for the rest of the run.
_REPORTED_OUTPUTS = outputs.reported_outputs


def _node(paths):
    """A node whose parms named in *paths* evaluate to the given path."""
    parms = {}
    for name, path in paths.items():
        parm = MagicMock()
        parm.eval.return_value = path
        parms[name] = parm
    node = MagicMock()
    node.parm.side_effect = parms.get
    return node


class TestFileCacheOutputs:
    def test_file_is_not_listed_beside_sopoutput(self, tmp_path):
        written = tmp_path / "cache.0001.bgeo.sc"
        written.write_bytes(b"x")
        node = _node(
            {
                "sopoutput": str(written),
                "file": str(tmp_path / "unused.$F4.bgeo.sc"),
            }
        )
        entries = _REPORTED_OUTPUTS(node)
        assert [entry["parm"] for entry in entries] == ["sopoutput"]
        assert entries[0]["exists"] is True

    def test_file_alone_is_still_listed(self, tmp_path):
        path = str(tmp_path / "out.bgeo.sc")
        entries = _REPORTED_OUTPUTS(_node({"file": path}))
        assert [(entry["parm"], entry["path"]) for entry in entries] == [("file", path)]
