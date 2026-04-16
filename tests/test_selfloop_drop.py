from __future__ import annotations

import math

from roadgraph_builder.pipeline.build_graph import BuildParams, polylines_to_graph


def _loop_polyline(radius: float, center=(0.0, 0.0), n=32):
    cx, cy = center
    return [
        (cx + radius * math.cos(2 * math.pi * i / n), cy + radius * math.sin(2 * math.pi * i / n))
        for i in range(n + 1)
    ]


def test_degenerate_selfloop_is_dropped():
    tiny_loop = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (0.0, 0.0)]
    straight = [(20.0, 0.0), (30.0, 0.0), (40.0, 0.0)]
    g = polylines_to_graph([tiny_loop, straight], BuildParams(merge_endpoint_m=5.0))

    assert len(g.edges) == 1
    edge = g.edges[0]
    assert edge.start_node_id != edge.end_node_id
    assert {n.id for n in g.nodes} == {edge.start_node_id, edge.end_node_id}


def test_legitimate_loop_is_kept():
    big_loop = _loop_polyline(radius=50.0, center=(100.0, 0.0), n=48)
    g = polylines_to_graph([big_loop], BuildParams(merge_endpoint_m=5.0))

    assert len(g.edges) == 1
    edge = g.edges[0]
    assert edge.start_node_id == edge.end_node_id
    # Arc length ~ 2 * pi * 50 ≈ 314 m, way above the 2*merge threshold.
    assert len(edge.polyline) >= 48
    loop_node = next(n for n in g.nodes if n.id == edge.start_node_id)
    assert loop_node.attributes["junction_hint"] == "self_loop"
    assert loop_node.attributes["degree"] == 2


def test_self_loop_with_additional_branch_is_multi_branch():
    big_loop = _loop_polyline(radius=50.0, center=(100.0, 0.0), n=48)
    # big_loop starts and ends at (center + (radius, 0)) = (150, 0).
    # Attach a straight branch that terminates at that same point.
    branch = [(220.0, 0.0), (185.0, 0.0), (150.0, 0.0)]
    g = polylines_to_graph([big_loop, branch], BuildParams(merge_endpoint_m=5.0))

    assert len(g.edges) == 2
    loop_edge = next(e for e in g.edges if e.start_node_id == e.end_node_id)
    loop_node = next(n for n in g.nodes if n.id == loop_edge.start_node_id)
    # Loop (degree 2) + branch (degree 1) → total 3 → multi_branch, not self_loop.
    assert loop_node.attributes["junction_hint"] == "multi_branch"
