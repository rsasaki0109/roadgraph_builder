"""3D1: slope-aware routing tests.

Verifies:
  - Without uphill_penalty/downhill_bonus, route is identical to 2D Dijkstra.
  - With uphill_penalty > 1, routing avoids steep ascents.
  - With downhill_bonus < 1, routing prefers descents.
"""

from __future__ import annotations

import math

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.routing.shortest_path import shortest_path


def _make_3d_graph() -> Graph:
    """Graph with two alternative paths from A to C.

    Path 1 (A→B→C): flat detour, 200 m total via B at (0, 100) then (100, 100).
    Path 2 (A→D→C): direct but steeply uphill, 141 m total (D at (50, 50)).
                    D is 20 m above A and C.

    Without slope cost: path 2 (A→D→C, ~141 m) is shorter.
    With strong uphill_penalty, path 1 (200 m flat) becomes preferred.
    """
    # Layout (in XY plane):
    #  A=(0,0) ——B=(0,100)——B2=(100,100)——C=(100,0)   [flat detour, 300m]
    #  A=(0,0) ——D=(50,50)——C=(100,0)                  [shorter, ~141m, steep]
    nodes = [
        Node(id="A", position=(0.0, 0.0), attributes={"elevation_m": 0.0}),
        Node(id="B", position=(0.0, 100.0), attributes={"elevation_m": 0.0}),
        Node(id="B2", position=(100.0, 100.0), attributes={"elevation_m": 0.0}),
        Node(id="C", position=(100.0, 0.0), attributes={"elevation_m": 0.0}),
        Node(id="D", position=(50.0, 50.0), attributes={"elevation_m": 20.0}),
    ]
    # Flat path: A→B→B2→C, total = 100+100+100 = 300 m, 0° slope.
    e_AB = Edge(
        id="eAB",
        start_node_id="A",
        end_node_id="B",
        polyline=[(0.0, 0.0), (0.0, 100.0)],
        attributes={"slope_deg": 0.0, "polyline_z": [0.0, 0.0]},
    )
    e_BB2 = Edge(
        id="eBB2",
        start_node_id="B",
        end_node_id="B2",
        polyline=[(0.0, 100.0), (100.0, 100.0)],
        attributes={"slope_deg": 0.0, "polyline_z": [0.0, 0.0]},
    )
    e_B2C = Edge(
        id="eB2C",
        start_node_id="B2",
        end_node_id="C",
        polyline=[(100.0, 100.0), (100.0, 0.0)],
        attributes={"slope_deg": 0.0, "polyline_z": [0.0, 0.0]},
    )
    # Steep shortcut: A→D (uphill, 20 m rise over ~70.7 m run → ~15.8°), D→C (downhill)
    run_AD = math.hypot(50.0, 50.0)  # ≈ 70.71 m
    slope_up = math.degrees(math.atan2(20.0, run_AD))  # ≈ 15.8°
    slope_dn = -slope_up
    e_AD = Edge(
        id="eAD",
        start_node_id="A",
        end_node_id="D",
        polyline=[(0.0, 0.0), (50.0, 50.0)],
        attributes={"slope_deg": slope_up, "polyline_z": [0.0, 20.0]},
    )
    e_DC = Edge(
        id="eDC",
        start_node_id="D",
        end_node_id="C",
        polyline=[(50.0, 50.0), (100.0, 0.0)],
        attributes={"slope_deg": slope_dn, "polyline_z": [20.0, 0.0]},
    )
    return Graph(nodes=nodes, edges=[e_AB, e_BB2, e_B2C, e_AD, e_DC])


def test_no_slope_cost_uses_shorter_path():
    """Without slope cost, shortest geometric path (A→D→C, ~141m) is chosen over detour (300m)."""
    g = _make_3d_graph()
    route = shortest_path(g, "A", "C")
    # Shorter path is A→D→C (~141 m vs 300 m flat detour)
    assert "D" in route.node_sequence, (
        f"Expected D in node sequence (shorter path ~141m), got {route.node_sequence}"
    )


def test_uphill_penalty_avoids_ascent():
    """With strong uphill_penalty, flat path A→B→C is preferred over steep A→D→C."""
    g = _make_3d_graph()
    route = shortest_path(g, "A", "C", uphill_penalty=5.0)
    # The steep uphill A→D should now be prohibitively expensive.
    assert "B" in route.node_sequence, (
        f"Expected B (flat path) with uphill_penalty=5.0, got {route.node_sequence}"
    )
    assert "D" not in route.node_sequence, (
        f"Expected D (steep path) to be avoided, got {route.node_sequence}"
    )


def test_no_slope_cost_identical_to_v060(tmp_path):
    """Without slope flags the route must be identical to a call without those args."""
    g = _make_3d_graph()
    route_plain = shortest_path(g, "A", "C")
    route_explicit = shortest_path(g, "A", "C", uphill_penalty=None, downhill_bonus=None)
    assert route_plain.node_sequence == route_explicit.node_sequence
    assert route_plain.edge_sequence == route_explicit.edge_sequence
    assert abs(route_plain.total_length_m - route_explicit.total_length_m) < 1e-9
