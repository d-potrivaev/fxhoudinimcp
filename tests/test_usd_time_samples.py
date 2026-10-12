"""get_usd_attribute on a time-sampled attribute answered `value: null`.

A PointInstancer's `positions` / `protoIndices`, authored per frame, have
nothing in the default slot, so Get() with the default time code returns
None: `is_authored: true` next to `value: null` read as "the attribute is
empty". With no time given and samples present, the current frame is read
(the first sample when the frame is outside the sampled range), and the
reply names the time used and the samples found.

get_usd_prim had the same default-slot read for every attribute: a
RenderSettings whose `resolution` had a default of (2048, 1080) and samples
of (1920, 1080) at frame 1 and (1280, 720) at frame 24 answered (2048, 1080)
on frame 24, a value the render of that frame never uses. It now reads every
attribute at `time` or the current frame, and a sampled attribute says so.

hou and pxr are mocked here; the live check ran on Houdini 22.0.429.
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
import fxhoudinimcp_server.handlers.lops_handlers as lops  # noqa: E402

# Shared with the other USD handler tests.
from _usd_fakes import attribute, prim_with, relationship, usd_module  # noqa: E402


class _Attr:
    """A Usd.Attribute whose Get() answers per time code, None on default."""

    def __init__(self, samples=(), values=None, type_name="point3f[]"):
        self._samples = list(samples)
        self._values = values or {}
        self._type = type_name

    def IsValid(self):
        return True

    def IsAuthored(self):
        return True

    def GetTypeName(self):
        return self._type

    def GetTimeSamples(self):
        return self._samples

    def Get(self, time_code):
        return self._values.get(getattr(time_code, "value", None))


def _stage(monkeypatch, attr, frame=12.0):
    prim = MagicMock()
    prim.IsValid.return_value = True
    prim.GetAttribute.return_value = attr
    stage = MagicMock()
    stage.GetPrimAtPath.return_value = prim
    monkeypatch.setattr(lops, "_get_lop_stage", lambda node_path: stage)
    usd = MagicMock()
    usd.TimeCode.side_effect = lambda t: MagicMock(value=t)
    usd.TimeCode.Default.return_value = MagicMock(value=None)
    monkeypatch.setattr(lops, "Usd", usd, raising=False)
    monkeypatch.setattr(lops.hou, "frame", lambda: frame)


@pytest.fixture
def sampled():
    return _Attr(samples=[1.0, 24.0], values={1.0: [1, 2, 3], 12.0: [4, 5, 6]})


class TestTimeSampledAttributes:
    def test_no_time_reads_the_current_frame_and_says_so(self, monkeypatch, sampled):
        _stage(monkeypatch, sampled)
        reply = lops._get_usd_attribute(
            node_path="/stage/pi", prim_path="/pi", attr_name="positions"
        )
        assert reply["value"] == [4, 5, 6]
        assert reply["time"] == 12.0
        assert reply["requested_time"] is None
        assert reply["time_source"] == "stage_frame"
        assert reply["time_samples"] == 2
        assert reply["time_range"] == [1.0, 24.0]
        assert "time-sampled" in reply["note"]

    def test_a_frame_outside_the_samples_falls_back_to_the_first(self, monkeypatch, sampled):
        _stage(monkeypatch, sampled, frame=900.0)
        reply = lops._get_usd_attribute(
            node_path="/stage/pi", prim_path="/pi", attr_name="positions"
        )
        assert reply["value"] == [1, 2, 3]
        assert reply["time"] == 1.0
        assert reply["time_source"] == "first_sample"

    def test_an_explicit_time_is_honoured_without_a_note(self, monkeypatch, sampled):
        _stage(monkeypatch, sampled)
        reply = lops._get_usd_attribute(
            node_path="/stage/pi", prim_path="/pi", attr_name="positions", time=1.0
        )
        assert reply["value"] == [1, 2, 3]
        assert reply["time"] == 1.0
        assert reply["time_source"] == "requested"
        assert reply["time_samples"] == 2
        assert "note" not in reply

    def test_a_static_attribute_reads_the_default_slot_as_before(self, monkeypatch):
        _stage(monkeypatch, _Attr(values={None: "rightHanded"}, type_name="token"))
        reply = lops._get_usd_attribute(
            node_path="/stage/x", prim_path="/p", attr_name="orientation"
        )
        assert reply["value"] == "rightHanded"
        assert reply["time"] is None
        assert reply["time_source"] == "default"
        assert "time_samples" not in reply
        assert "note" not in reply


@pytest.fixture
def motion_blurred():
    """Velocity samples at the subframes motion blur writes around frame 20."""
    times = [19.75, 20.0, 20.25]
    return _Attr(samples=times, values={t: [t, 0.0, 0.0] for t in times}, type_name="vector3f")


class TestSampleTimes:
    def test_the_times_themselves_are_listed(self, monkeypatch, motion_blurred):
        _stage(monkeypatch, motion_blurred, frame=20.0)
        reply = lops._get_usd_attribute(node_path="/stage/v", prim_path="/p", attr_name="v")
        assert reply["sample_times"] == [19.75, 20.0, 20.25]
        assert "sample_times_truncated" not in reply
        assert "samples" not in reply

    def test_all_samples_reads_the_value_at_each_time(self, monkeypatch, motion_blurred):
        _stage(monkeypatch, motion_blurred, frame=20.0)
        reply = lops._get_usd_attribute(
            node_path="/stage/v", prim_path="/p", attr_name="v", all_samples=True
        )
        assert reply["samples"] == [
            {"time": 19.75, "value": [19.75, 0.0, 0.0]},
            {"time": 20.0, "value": [20.0, 0.0, 0.0]},
            {"time": 20.25, "value": [20.25, 0.0, 0.0]},
        ]
        assert reply["value"] == [20.0, 0.0, 0.0]

    def test_a_long_run_of_samples_is_capped_and_says_so(self, monkeypatch):
        times = [float(t) for t in range(1, lops._SAMPLE_CAP + 11)]
        _stage(monkeypatch, _Attr(samples=times, values={t: t for t in times}, type_name="float"))
        reply = lops._get_usd_attribute(
            node_path="/stage/x", prim_path="/p", attr_name="f", time=1.0, all_samples=True
        )
        assert reply["time_samples"] == lops._SAMPLE_CAP + 10
        assert reply["sample_times"] == times[: lops._SAMPLE_CAP]
        assert reply["sample_times_truncated"] is True
        assert len(reply["samples"]) == lops._SAMPLE_CAP

    def test_the_window_follows_the_time_read(self, monkeypatch):
        # 5000 samples read at frame 1000: the first 64 said nothing about it.
        times = [1.0 + i * 0.25 for i in range(5000)]
        _stage(monkeypatch, _Attr(samples=times, values={t: t for t in times}, type_name="float"))
        reply = lops._get_usd_attribute(
            node_path="/stage/x", prim_path="/p", attr_name="f", time=1000.0
        )
        window = reply["sample_times"]
        assert len(window) == lops._SAMPLE_CAP
        assert window[0] < 1000.0 < window[-1]
        assert times[reply["sample_times_start"]] == window[0]

    def test_a_long_array_per_sample_is_summarised_and_full_refused(self, monkeypatch):
        big = list(range(lops._ARRAY_SUMMARY_LIMIT + 4))
        _stage(monkeypatch, _Attr(samples=[1.0], values={1.0: big}, type_name="int[]"))
        reply = lops._get_usd_attribute(
            node_path="/stage/x", prim_path="/p", attr_name="ids", time=1.0, all_samples=True
        )
        assert isinstance(reply["samples"][0]["value"], dict)
        with pytest.raises(ValueError, match="all_samples"):
            lops._get_usd_attribute(
                node_path="/stage/x",
                prim_path="/p",
                attr_name="ids",
                time=1.0,
                all_samples=True,
                full=True,
            )

    def test_a_static_attribute_lists_no_times(self, monkeypatch):
        _stage(monkeypatch, _Attr(values={None: "rightHanded"}, type_name="token"))
        reply = lops._get_usd_attribute(
            node_path="/stage/x", prim_path="/p", attr_name="orientation", all_samples=True
        )
        assert "sample_times" not in reply
        assert "samples" not in reply

    def test_the_tool_forwards_all_samples(self, mock_ctx, mock_bridge):
        import asyncio

        from fxhoudinimcp.tools.lops import get_usd_attribute

        asyncio.run(get_usd_attribute(mock_ctx, "/stage/v", "/p", "v", all_samples=True))
        command, params = mock_bridge.execute.call_args[0][:2]
        assert command == "lops.get_usd_attribute"
        assert params["all_samples"] is True
        asyncio.run(get_usd_attribute(mock_ctx, "/stage/v", "/p", "v"))
        assert "all_samples" not in mock_bridge.execute.call_args[0][1]


@pytest.fixture
def render_settings(monkeypatch):
    """A RenderSettings prim: sampled resolution, a static token, a camera."""
    settings = prim_with(
        "/Render/rendersettings",
        "RenderSettings",
        attributes=[
            attribute("resolution", [2048, 1080], {1.0: [1920, 1080], 24.0: [1280, 720]}),
            attribute("aspectRatioConformPolicy", "expandAperture", type_name="token"),
        ],
        relationships=[relationship("camera", ["/cameras/cam1"])],
    )
    settings.GetChildren.return_value = ()
    stage = MagicMock()
    stage.GetPrimAtPath.return_value = settings
    monkeypatch.setattr(lops, "_get_lop_stage", lambda node_path: stage)
    monkeypatch.setattr(lops, "Usd", usd_module(), raising=False)
    monkeypatch.setattr(lops.hou, "frame", lambda: 24.0)
    return settings


def _read(**kwargs):
    reply = lops._get_usd_prim(node_path="/stage/krs", prim_path="/Render/rendersettings", **kwargs)
    attrs = {a["name"]: a for a in reply["prim"]["attributes"]}
    return reply, attrs


class TestGetUsdPrimReadsAtTheFrame:
    def test_no_time_reads_the_current_frame_not_the_default_slot(self, render_settings):
        reply, attrs = _read()
        assert attrs["resolution"]["value"] == [1280, 720]
        assert attrs["resolution"]["time_samples"] == 2
        assert reply["time"] == 24.0
        assert reply["time_source"] == "stage_frame"

    def test_a_static_attribute_carries_no_sample_count(self, render_settings):
        _, attrs = _read()
        assert attrs["aspectRatioConformPolicy"]["value"] == "expandAperture"
        assert "time_samples" not in attrs["aspectRatioConformPolicy"]

    def test_an_explicit_time_is_honoured(self, render_settings):
        reply, attrs = _read(time=1)
        assert attrs["resolution"]["value"] == [1920, 1080]
        assert reply["time"] == 1.0
        assert reply["time_source"] == "requested"

    def test_without_a_frame_the_default_slot_is_read_and_named(self, monkeypatch, render_settings):
        def no_frame():
            raise RuntimeError("no frame")

        monkeypatch.setattr(lops.hou, "frame", no_frame)
        reply, attrs = _read()
        assert attrs["resolution"]["value"] == [2048, 1080]
        assert reply["time"] is None
        assert reply["time_source"] == "default"

    def test_relationships_are_listed_with_their_targets(self, render_settings):
        reply, _ = _read()
        assert reply["prim"]["relationships"] == [
            {"name": "camera", "relationship": True, "targets": ["/cameras/cam1"]}
        ]

    def test_attr_patterns_narrow_attributes_and_relationships(self, render_settings):
        reply, attrs = _read(attr_patterns=["res*"])
        assert list(attrs) == ["resolution"]
        assert reply["prim"]["relationships"] == []
        reply, attrs = _read(attr_patterns=["camera"])
        assert attrs == {}
        assert [r["name"] for r in reply["prim"]["relationships"]] == ["camera"]
