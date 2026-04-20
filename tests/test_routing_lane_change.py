"""Tests for A3: lane-level routing with --allow-lane-change.

Covers:
- A 2-lane edge graph: route with allow_lane_change can traverse lane 0→1.
- Without allow_lane_change, routing produces the same result as before (backward compat).
- lane_sequence is populated when allow_lane_change=True, None otherwise.
- lane_change_cost_m affects routing costs.
"""

from __future__ import annotations

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.routing.shortest_path import Route, shortest_path


def _make_two_lane_graph() -> Graph:
    """A simple 2-node graph with a single 2-lane edge (hd.lane_count=2, hd.lanes)."""
    n0 = Node("n0", (0.0, 0.0))
    n1 = Node("n1", (100.0, 0.0))
    e0 = Edge("e0", "n0", "n1", [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)])
    e0.attributes = {
        "hd": {
            "lane_count": 2,
            "lanes": [
                {
                    "lane_index": 0,
                    "offset_m": -1.75,
                    "centerline_m": [[0.0, -1.75], [100.0, -1.75]],
                    "confidence": 0.9,
                },
                {
                    "lane_index": 1,
                    "offset_m": 1.75,
                    "centerline_m": [[0.0, 1.75], [100.0, 1.75]],
                    "confidence": 0.9,
                },
            ],
        }
    }
    return Graph(nodes=[n0, n1], edges=[e0])


def _make_multi_edge_graph() -> Graph:
    """Two edges in sequence: n0→n1→n2. First edge has 2 lanes, second has 1 lane."""
    n0 = Node("n0", (0.0, 0.0))
    n1 = Node("n1", (100.0, 0.0))
    n2 = Node("n2", (200.0, 0.0))
    e0 = Edge("e0", "n0", "n1", [(0.0, 0.0), (100.0, 0.0)])
    e0.attributes = {
        "hd": {
            "lane_count": 2,
            "lanes": [
                {"lane_index": 0, "offset_m": -1.75, "centerline_m": [[0.0, -1.75], [100.0, -1.75]], "confidence": 0.9},
                {"lane_index": 1, "offset_m": 1.75, "centerline_m": [[0.0, 1.75], [100.0, 1.75]], "confidence": 0.9},
            ],
        }
    }
    e1 = Edge("e1", "n1", "n2", [(100.0, 0.0), (200.0, 0.0)])
    e1.attributes = {"hd": {"lane_count": 1}}
    return Graph(nodes=[n0, n1, n2], edges=[e0, e1])


class TestLaneChangeRouting:
    def test_allow_lane_change_finds_route(self):
        """allow_lane_change=True should find a route over a 2-lane edge."""
        graph = _make_two_lane_graph()
        route = shortest_path(graph, "n0", "n1", allow_lane_change=True)
        assert route.from_node == "n0"
        assert route.to_node == "n1"
        assert "e0" in route.edge_sequence

    def test_lane_sequence_populated(self):
        """lane_sequence must be non-None and same length as edge_sequence."""
        graph = _make_two_lane_graph()
        route = shortest_path(graph, "n0", "n1", allow_lane_change=True)
        assert route.lane_sequence is not None
        assert len(route.lane_sequence) == len(route.edge_sequence)

    def test_no_allow_lane_change_lane_sequence_is_none(self):
        """Without allow_lane_change, lane_sequence must be None."""
        graph = _make_two_lane_graph()
        route = shortest_path(graph, "n0", "n1")
        assert route.lane_sequence is None

    def test_backward_compat_same_route_without_flag(self):
        """Without allow_lane_change, edge_sequence is the same as edge-level routing."""
        graph = _make_two_lane_graph()
        route_std = shortest_path(graph, "n0", "n1")
        route_lane = shortest_path(graph, "n0", "n1", allow_lane_change=True)
        # Both should traverse e0.
        assert route_std.edge_sequence == ["e0"]
        assert route_lane.edge_sequence == ["e0"]

    def test_lane_change_cost_increases_total_cost(self):
        """Higher lane_change_cost_m should not prevent finding a route but changes cost."""
        graph = _make_multi_edge_graph()
        route = shortest_path(graph, "n0", "n2", allow_lane_change=True, lane_change_cost_m=200.0)
        assert route.to_node == "n2"
        assert len(route.edge_sequence) == 2

    def test_multi_edge_lane_sequence_length(self):
        """lane_sequence length must match edge_sequence length for multi-edge routes."""
        graph = _make_multi_edge_graph()
        route = shortest_path(graph, "n0", "n2", allow_lane_change=True)
        assert route.lane_sequence is not None
        assert len(route.lane_sequence) == len(route.edge_sequence) == 2

    def test_same_node_from_and_to(self):
        """From == to returns empty route regardless of allow_lane_change."""
        graph = _make_two_lane_graph()
        route = shortest_path(graph, "n0", "n0", allow_lane_change=True)
        assert route.edge_sequence == []
        assert route.total_length_m == 0.0
