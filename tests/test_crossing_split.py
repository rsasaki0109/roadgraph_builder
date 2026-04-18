from __future__ import annotations

from roadgraph_builder.pipeline.build_graph import BuildParams, polylines_to_graph
from roadgraph_builder.utils.geometry import (
    _segment_segment_intersection,
    split_polylines_at_crossings,
)


def test_segment_intersection_cross_at_origin():
    pt = _segment_segment_intersection((-1.0, 0.0), (1.0, 0.0), (0.0, -1.0), (0.0, 1.0))
    assert pt == (0.0, 0.0)


def test_segment_intersection_rejects_endpoint_touch():
    # Segments touch at a shared endpoint — not a strict interior crossing.
    pt = _segment_segment_intersection((0.0, 0.0), (1.0, 0.0), (1.0, 0.0), (1.0, 1.0))
    assert pt is None


def test_segment_intersection_rejects_parallel():
    pt = _segment_segment_intersection((0.0, 0.0), (2.0, 0.0), (0.0, 1.0), (2.0, 1.0))
    assert pt is None


def test_split_polylines_at_crossings_creates_four_halves():
    # Vertices intentionally avoid (0, 0) so the crossing is strictly interior
    # to one segment of each polyline.
    horiz = [(-50.0, 0.0), (-10.0, 0.0), (10.0, 0.0), (50.0, 0.0)]
    vert = [(0.0, -50.0), (0.0, -10.0), (0.0, 10.0), (0.0, 50.0)]
    out = split_polylines_at_crossings([horiz, vert])
    # Both polylines split at origin → 4 halves total.
    assert len(out) == 4
    # Every sub-polyline should touch the origin either as start or end.
    for sub in out:
        assert (0.0, 0.0) in sub


def test_split_polylines_at_crossings_ignores_non_crossing():
    a = [(0.0, 0.0), (10.0, 0.0)]
    b = [(0.0, 1.0), (10.0, 1.0)]
    out = split_polylines_at_crossings([a, b])
    assert out == [a, b]


def test_build_graph_classifies_crossroads_from_x_crossing():
    horiz = [(-50.0, 0.0), (-10.0, 0.0), (10.0, 0.0), (50.0, 0.0)]
    vert = [(0.0, -50.0), (0.0, -10.0), (0.0, 10.0), (0.0, 50.0)]
    g = polylines_to_graph([horiz, vert], BuildParams(merge_endpoint_m=5.0))
    assert len(g.edges) == 4
    multi = [n for n in g.nodes if n.attributes.get("junction_hint") == "multi_branch"]
    assert len(multi) == 1
    # Perpendicular cross → crossroads (t_junction family only kicks in at degree 3).
    assert multi[0].attributes.get("junction_type") == "crossroads"
