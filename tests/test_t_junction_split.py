from __future__ import annotations

import math

from roadgraph_builder.pipeline.build_graph import BuildParams, polylines_to_graph
from roadgraph_builder.utils.geometry import split_polylines_at_t_junctions


def _straight(p0, p1, n=11):
    return [
        (
            p0[0] + (p1[0] - p0[0]) * i / (n - 1),
            p0[1] + (p1[1] - p0[1]) * i / (n - 1),
        )
        for i in range(n)
    ]


def test_t_junction_splits_main_road():
    main = _straight((-50.0, 0.0), (50.0, 0.0), n=21)
    branch = _straight((0.0, -30.0), (0.0, 0.0), n=11)
    split = split_polylines_at_t_junctions([main, branch], merge_threshold_m=5.0)
    # The branch is untouched (its endpoint is already at the intersection);
    # the main road gets split into two halves at (0, 0).
    assert len(split) == 3
    has_split_at_origin = sum(
        1
        for pl in split
        if any(abs(p[0]) < 1e-6 and abs(p[1]) < 1e-6 for p in pl)
    )
    assert has_split_at_origin >= 2  # both halves now anchor at (0,0)


def test_no_split_when_endpoint_beyond_threshold():
    main = _straight((-50.0, 0.0), (50.0, 0.0), n=21)
    # Branch endpoint lands 20 m from the main road — beyond merge threshold.
    branch = _straight((0.0, -30.0), (0.0, -20.0), n=11)
    split = split_polylines_at_t_junctions([main, branch], merge_threshold_m=5.0)
    assert len(split) == 2


def test_no_split_near_main_endpoint():
    # Branch endpoint sits at the MAIN road's tip (x≈-50).
    main = _straight((-50.0, 0.0), (50.0, 0.0), n=21)
    branch = _straight((-51.0, -30.0), (-51.0, 0.0), n=11)
    split = split_polylines_at_t_junctions([main, branch], merge_threshold_m=5.0, min_interior_m=3.0)
    # min_interior_m guards against splitting at the tip — the main road
    # should remain a single polyline because endpoint merging already
    # handles tip-to-tip fusion.
    assert len(split) == 2


def test_build_graph_connects_t_junction_into_multi_branch():
    main = _straight((-50.0, 0.0), (50.0, 0.0), n=21)
    branch = _straight((0.0, -30.0), (0.0, 0.0), n=11)
    g = polylines_to_graph([main, branch], BuildParams(merge_endpoint_m=5.0))
    # 3 edges and at least one multi_branch node at the split point.
    assert len(g.edges) == 3
    multi = [n for n in g.nodes if n.attributes.get("junction_hint") == "multi_branch"]
    assert len(multi) == 1
    jtype = multi[0].attributes.get("junction_type")
    assert jtype == "t_junction"
    # The multi_branch node should be at the origin where we split.
    assert math.isclose(multi[0].position[0], 0.0, abs_tol=0.5)
    assert math.isclose(multi[0].position[1], 0.0, abs_tol=0.5)
