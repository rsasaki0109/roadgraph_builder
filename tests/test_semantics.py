from __future__ import annotations

from roadgraph_builder.semantics import LaneKind, attach_lane_kind


def test_attach_lane_kind():
    a = attach_lane_kind({"source": "x"}, LaneKind.DRIVING)
    assert a["lane_kind"] == "driving"
    assert a["source"] == "x"
