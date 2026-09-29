"""get_attrib_stats refused vertex attributes.

uv and N usually live on vertices, and the UV range is the number that decides
a texture's tiling multiplier, yet attrib_class="vertex" answered "has no
per-element statistics". Vertex is now accepted; values come from one
{point,prim,vertex}{Float,Int}AttribValues call, element_count from the
geometry's intrinsics, and the per-element loop is only the fallback.

frames and node_paths measure several nodes over several frames in one call
and put the current frame back; percentiles add the distribution.

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
import fxhoudinimcp_server.handlers.geometry_handlers as geometry  # noqa: E402

hou = geometry.hou


def _attrib(name, size, data_type):
    attrib = MagicMock()
    attrib.name.return_value = name
    attrib.isArrayType.return_value = False
    attrib.dataType.return_value = data_type
    attrib.size.return_value = size
    return attrib


def _geometry(monkeypatch, counts):
    geo = MagicMock()
    geo.intrinsicValue.side_effect = lambda name: counts[name]
    monkeypatch.setattr(geometry, "_get_sop_geo", lambda path: geo)
    # hou is a MagicMock here, and an except clause needs a real class.
    monkeypatch.setattr(hou, "OperationFailed", RuntimeError)
    return geo


class TestVertexStatistics:
    def test_uv_on_vertices_has_a_range(self, monkeypatch):
        geo = _geometry(monkeypatch, {"vertexcount": 4})
        geo.vertexAttribs.return_value = [_attrib("uv", 3, hou.attribData.Float)]
        geo.vertexFloatAttribValues.return_value = [0, 0, 0, 1, 0, 0, 1, 4, 0, 0, 4, 0]
        result = geometry._get_attrib_stats(
            node_path="/obj/geo1/uvproject1", attribs=["uv"], attrib_class="vertex"
        )
        entry = result["stats"]["uv"]
        assert result["element_count"] == 4
        assert entry["count"] == 4
        assert entry["per_component"][0]["max"] == 1
        assert entry["per_component"][1]["max"] == 4
        geo.vertexFloatAttribValues.assert_called_once_with("uv")
        geo.prims.assert_not_called()  # the fast path, no per-vertex loop

    def test_vertices_fall_back_to_the_element_loop(self, monkeypatch):
        geo = _geometry(monkeypatch, {"vertexcount": 3})
        uv = _attrib("uv", 2, hou.attribData.Float)
        geo.vertexAttribs.return_value = [uv]
        geo.vertexFloatAttribValues.side_effect = AttributeError
        vertices = []
        for u in (-4.5, 0.5, 5.5):
            vertex = MagicMock()
            vertex.attribValue.return_value = (u, 0.5)
            vertices.append(vertex)
        prim = MagicMock()
        prim.vertices.return_value = vertices
        geo.prims.return_value = [prim]
        result = geometry._get_attrib_stats(
            node_path="/obj/geo1/uvproject1", attribs=["uv"], attrib_class="vertex"
        )
        entry = result["stats"]["uv"]
        assert entry["count"] == 3
        assert entry["per_component"][0] == {"min": -4.5, "max": 5.5, "mean": 0.5}
        assert entry["per_component"][1]["min"] == entry["per_component"][1]["max"] == 0.5


class TestFastPathsForEveryClass:
    def test_an_int_prim_attribute_reads_in_one_call(self, monkeypatch):
        geo = _geometry(monkeypatch, {"primitivecount": 3})
        geo.primAttribs.return_value = [_attrib("piece", 1, hou.attribData.Int)]
        geo.primIntAttribValues.return_value = [0, 2, 7]
        result = geometry._get_attrib_stats(
            node_path="/obj/geo1/out", attribs=["piece"], attrib_class="prim"
        )
        entry = result["stats"]["piece"]
        assert (entry["min"], entry["max"], entry["count"]) == (0, 7, 3)
        assert result["element_count"] == 3
        geo.primIntAttribValues.assert_called_once_with("piece")
        geo.prims.assert_not_called()

    def test_points_still_read_through_the_float_call(self, monkeypatch):
        geo = _geometry(monkeypatch, {"pointcount": 2})
        geo.pointAttribs.return_value = [_attrib("fuel", 1, hou.attribData.Float)]
        geo.pointFloatAttribValues.return_value = [0.25, 0.75]
        result = geometry._get_attrib_stats(node_path="/obj/geo1/out", attribs=["fuel"])
        assert result["stats"]["fuel"]["mean"] == pytest.approx(0.5)
        assert result["element_count"] == 2
        geo.points.assert_not_called()

    def test_element_count_falls_back_when_the_intrinsic_does_not_answer(self, monkeypatch):
        geo = _geometry(monkeypatch, {})  # every intrinsic lookup raises
        geo.pointAttribs.return_value = [_attrib("fuel", 1, hou.attribData.Float)]
        geo.pointFloatAttribValues.return_value = [1.0, 2.0, 3.0]
        geo.points.return_value = [object(), object(), object()]
        result = geometry._get_attrib_stats(node_path="/obj/geo1/out", attribs=["fuel"])
        assert result["element_count"] == 3


class TestStatsOverFramesAndNodes:
    """Several variants at a handful of frames took a call per node per frame."""

    @pytest.fixture
    def timeline(self, monkeypatch):
        state = {"frame": 7.0, "visited": []}
        monkeypatch.setattr(hou, "frame", lambda: state["frame"])

        def set_frame(frame):
            state["frame"] = frame
            state["visited"].append(frame)

        monkeypatch.setattr(hou, "setFrame", set_frame)

        def once(path, attribs, attrib_class, percentiles=None):
            if path.endswith("broken"):
                raise ValueError("no geometry")
            return {"node_path": path, "element_count": int(state["frame"]) * 10}

        monkeypatch.setattr(geometry, "_attrib_stats_once", once)
        return state

    def test_one_row_per_node_per_frame_in_increasing_order(self, timeline):
        result = geometry._get_attrib_stats(node_paths=["/a", "/b"], frames=[24, 1, 60])
        assert result["frames"] == [1.0, 24.0, 60.0]
        assert [(r["node_path"], r["frame"]) for r in result["rows"]] == [
            ("/a", 1.0),
            ("/b", 1.0),
            ("/a", 24.0),
            ("/b", 24.0),
            ("/a", 60.0),
            ("/b", 60.0),
        ]
        # Each row is measured at its own frame.
        assert result["rows"][-1]["element_count"] == 600

    def test_the_current_frame_is_put_back(self, timeline):
        result = geometry._get_attrib_stats(node_path="/a", frames=[1, 2])
        assert timeline["frame"] == 7.0
        assert timeline["visited"] == [1.0, 2.0, 7.0]
        assert result["frame_restored"] == 7.0

    def test_the_frame_is_put_back_when_a_measure_raises(self, timeline, monkeypatch):
        def explode(*args, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(geometry, "_attrib_stats_once", explode)
        with pytest.raises(KeyboardInterrupt):
            geometry._get_attrib_stats(node_path="/a", frames=[1, 2])
        assert timeline["frame"] == 7.0

    def test_a_failing_node_is_a_row_not_the_whole_call(self, timeline):
        result = geometry._get_attrib_stats(node_paths=["/a", "/broken"], frames=[1])
        assert result["rows"][0]["element_count"] == 10
        assert result["rows"][1] == {"node_path": "/broken", "error": "no geometry", "frame": 1.0}

    def test_several_nodes_without_frames_read_the_current_one(self, timeline):
        result = geometry._get_attrib_stats(node_paths=["/a", "/b"])
        assert result["frames"] == [7.0]
        assert len(result["rows"]) == 2

    def test_one_node_and_no_frames_keeps_the_single_answer(self, timeline):
        result = geometry._get_attrib_stats(node_path="/a")
        assert result == {"node_path": "/a", "element_count": 70}
        assert timeline["visited"] == []

    def test_node_paths_of_one_still_answers_rows(self, timeline):
        result = geometry._get_attrib_stats(node_paths=["/a"])
        assert [r["node_path"] for r in result["rows"]] == ["/a"]

    def test_node_path_and_node_paths_together_are_refused(self, timeline):
        with pytest.raises(ValueError, match="not both"):
            geometry._get_attrib_stats(node_path="/a", node_paths=["/b"])

    def test_no_node_is_refused(self):
        with pytest.raises(ValueError, match="node_paths"):
            geometry._get_attrib_stats(frames=[1])


class TestPercentiles:
    def test_out_of_range_is_refused(self):
        with pytest.raises(ValueError, match="0..100"):
            geometry._get_attrib_stats(node_path="/obj/geo1/out", percentiles=[150])

    def test_the_python_percentile_interpolates_like_numpy(self):
        values = [4.0, 1.0, 3.0, 2.0]
        assert geometry._python_percentile(values, 50) == pytest.approx(2.5)
        assert geometry._python_percentile(values, 25) == pytest.approx(1.75)
        assert geometry._python_percentile(values, 0) == 1.0
        assert geometry._python_percentile(values, 100) == 4.0

    def test_scalar_and_vector_percentiles_on_the_list_path(self, monkeypatch):
        geo = _geometry(monkeypatch, {"pointcount": 4})
        geo.pointAttribs.return_value = [
            _attrib("fuel", 1, hou.attribData.Float),
            _attrib("v", 2, hou.attribData.Float),
        ]
        values = {"fuel": [0.0, 1.0, 2.0, 3.0], "v": [0, 10, 1, 20, 2, 30, 3, 40]}
        geo.pointFloatAttribValues.side_effect = lambda name: values[name]
        result = geometry._get_attrib_stats(
            node_path="/obj/geo1/out", attribs=["fuel", "v"], percentiles=[50, 100]
        )
        assert result["stats"]["fuel"]["percentiles"] == {"50": 1.5, "100": 3.0}
        assert result["stats"]["v"]["percentiles"] == {"50": [1.5, 25.0], "100": [3.0, 40.0]}

    def test_no_percentiles_no_key(self, monkeypatch):
        geo = _geometry(monkeypatch, {"pointcount": 2})
        geo.pointAttribs.return_value = [_attrib("fuel", 1, hou.attribData.Float)]
        geo.pointFloatAttribValues.return_value = [0.25, 0.75]
        result = geometry._get_attrib_stats(node_path="/obj/geo1/out", attribs=["fuel"])
        assert "percentiles" not in result["stats"]["fuel"]


class TestClientTool:
    @pytest.mark.asyncio
    async def test_vertex_class_reaches_the_handler(self, mock_ctx, mock_bridge):
        from fxhoudinimcp.tools.geometry import get_attrib_stats

        await get_attrib_stats(
            mock_ctx, node_path="/obj/geo1/uvproject1", attribs=["uv"], attrib_class="vertex"
        )
        mock_bridge.execute.assert_called_once_with(
            "geometry.get_attrib_stats",
            {"node_path": "/obj/geo1/uvproject1", "attrib_class": "vertex", "attribs": ["uv"]},
        )

    @pytest.mark.asyncio
    async def test_frames_and_nodes_wait_for_the_cook(self, mock_ctx, mock_bridge):
        from fxhoudinimcp.bridge import NO_TIMEOUT
        from fxhoudinimcp.tools.geometry import get_attrib_stats

        await get_attrib_stats(
            mock_ctx,
            node_paths=["/obj/a/out", "/obj/b/out"],
            frames=[1, 24],
            attribs=["P"],
            percentiles=[50],
        )
        mock_bridge.execute.assert_called_once_with(
            "geometry.get_attrib_stats",
            {
                "attrib_class": "point",
                "attribs": ["P"],
                "frames": [1, 24],
                "node_paths": ["/obj/a/out", "/obj/b/out"],
                "percentiles": [50],
            },
            timeout=NO_TIMEOUT,
        )
