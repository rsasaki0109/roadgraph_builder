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
