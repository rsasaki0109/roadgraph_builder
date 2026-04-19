"""Tests for uncertainty-aware routing (ROADMAP_0.6.md §ε).

A 4-node graph with two alternative paths between n0 and n3:
  Path A (observed):   n0 → n1 → n3, two edges of 10 m each = 20 m total
  Path B (unobserved): n0 → n2 → n3, two edges of 10 m each = 20 m total

Both paths have identical length, so:
  - Default (no hooks): path selection is non-deterministic by length → we just
    check it terminates and returns 20 m.
  - prefer_observed=True: Path A has trace_observation_count > 0, so it is preferred.
  - min_confidence: edges on Path A have confidence=0.3, Path B has confidence=0.8.
    With min_confidence=0.5, Path A edges are excluded → Path B is used.
    With min_confidence=0.9, no path is reachable → ValueError.
"""

from __future__ import annotations

import math
import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.routing.shortest_path import Route, shortest_path


# ---------------------------------------------------------------------------
# Graph fixture
# ---------------------------------------------------------------------------


def _make_4node_graph(
    *,
    path_a_observed: bool = True,
    path_a_confidence: float | None = None,
    path_b_confidence: float | None = None,
) -> Graph:
    """Create a 4-node graph with two equal-length paths.

    Path A: n0 → n1 → n3 (edges e01, e13)
    Path B: n0 → n2 → n3 (edges e02, e23)

    Each edge has length = 10 m.

    Args:
        path_a_observed: If True, edges on Path A have trace_observation_count=5.
        path_a_confidence: If set, Path A edges have hd_refinement.confidence=this.
        path_b_confidence: If set, Path B edges have hd_refinement.confidence=this.
    """
    def _make_attrs(observed: bool, confidence: float | None) -> dict:
        attrs: dict = {}
        if observed:
            attrs["trace_stats"] = {"trace_observation_count": 5, "matched_samples": 10}
        else:
            attrs["trace_stats"] = {"trace_observation_count": 0, "matched_samples": 0}
        if confidence is not None:
            attrs["hd"] = {
                "hd_refinement": {"confidence": confidence}
            }
        return attrs

    nodes = [
        Node("n0", (0.0, 0.0)),
        Node("n1", (10.0, 5.0)),
        Node("n2", (10.0, -5.0)),
        Node("n3", (20.0, 0.0)),
    ]
    # Path A edges (10 m each, Pythagorean: sqrt(100+25)=sqrt(125)≈11.18 actual)
    # Use axis-aligned edges for exact 10 m lengths.
    e01 = Edge("e01", "n0", "n1", [(0.0, 0.0), (10.0, 0.0)])
    e01.attributes = _make_attrs(path_a_observed, path_a_confidence)
    e13 = Edge("e13", "n1", "n3", [(10.0, 0.0), (20.0, 0.0)])
    e13.attributes = _make_attrs(path_a_observed, path_a_confidence)

    # Path B edges
    e02 = Edge("e02", "n0", "n2", [(0.0, 0.0), (10.0, 0.0)])
    e02.attributes = _make_attrs(False, path_b_confidence)
    e23 = Edge("e23", "n2", "n3", [(10.0, 0.0), (20.0, 0.0)])
    e23.attributes = _make_attrs(False, path_b_confidence)

    return Graph(nodes=nodes, edges=[e01, e13, e02, e23])


# ---------------------------------------------------------------------------
# Tests: default behavior (backward compat)
# ---------------------------------------------------------------------------


class TestDefaultBehavior:
    def test_default_returns_a_route(self):
        g = _make_4node_graph()
        r = shortest_path(g, "n0", "n3")
        assert isinstance(r, Route)
        assert r.from_node == "n0"
        assert r.to_node == "n3"

    def test_default_total_length_is_20m(self):
        """Both paths are 10+10=20 m; default should return 20 m."""
        g = _make_4node_graph()
        r = shortest_path(g, "n0", "n3")
        assert math.isclose(r.total_length_m, 20.0, abs_tol=0.01)

    def test_same_node_returns_empty_route(self):
        g = _make_4node_graph()
        r = shortest_path(g, "n0", "n0")
        assert r.edge_sequence == []
        assert r.total_length_m == 0.0

    def test_no_hooks_does_not_crash_with_confidence(self):
        """Even when edges have confidence data, default routing ignores it."""
        g = _make_4node_graph(path_a_confidence=0.3, path_b_confidence=0.9)
        r = shortest_path(g, "n0", "n3")
        assert r is not None


# ---------------------------------------------------------------------------
# Tests: prefer_observed
# ---------------------------------------------------------------------------


class TestPreferObserved:
    def test_prefers_observed_path(self):
        """With prefer_observed, Path A (observed) beats Path B (unobserved)
        even when both have the same length."""
        g = _make_4node_graph(path_a_observed=True)
        r = shortest_path(g, "n0", "n3", prefer_observed=True)
        # Path A uses edges e01 + e13.
        assert set(r.edge_sequence) == {"e01", "e13"}

    def test_total_length_is_actual_meters_not_weighted_cost(self):
        """total_length_m must be real arc length (20 m), not the weighted cost."""
        g = _make_4node_graph(path_a_observed=True)
        r = shortest_path(g, "n0", "n3", prefer_observed=True)
        # True arc length of two 10-m edges = 20 m.
        assert math.isclose(r.total_length_m, 20.0, abs_tol=0.01)

    def test_custom_bonus_penalty(self):
        """Custom bonus/penalty values still route to the observed path."""
        g = _make_4node_graph(path_a_observed=True)
        r = shortest_path(
            g, "n0", "n3",
            prefer_observed=True,
            observed_bonus=0.1,
            unobserved_penalty=5.0,
        )
        assert set(r.edge_sequence) == {"e01", "e13"}

    def test_unobserved_chosen_when_no_observed(self):
        """When no edges are observed, routing still finds a path."""
        g = _make_4node_graph(path_a_observed=False)
        r = shortest_path(g, "n0", "n3", prefer_observed=True)
        assert r is not None
        assert math.isclose(r.total_length_m, 20.0, abs_tol=0.01)


# ---------------------------------------------------------------------------
# Tests: min_confidence
# ---------------------------------------------------------------------------


class TestMinConfidence:
    def test_min_confidence_excludes_low_confidence_edges(self):
        """min_confidence=0.5 excludes Path A (conf=0.3) → Path B (conf=0.8) used."""
        g = _make_4node_graph(path_a_confidence=0.3, path_b_confidence=0.8)
        r = shortest_path(g, "n0", "n3", min_confidence=0.5)
        assert set(r.edge_sequence) == {"e02", "e23"}

    def test_min_confidence_too_strict_raises_value_error(self):
        """When all edges are below min_confidence, ValueError is raised."""
        g = _make_4node_graph(path_a_confidence=0.3, path_b_confidence=0.3)
        with pytest.raises(ValueError, match="no path"):
            shortest_path(g, "n0", "n3", min_confidence=0.9)

    def test_min_confidence_none_has_no_effect(self):
        """min_confidence=None means no filtering (backward compat)."""
        g = _make_4node_graph(path_a_confidence=0.3, path_b_confidence=0.8)
        r = shortest_path(g, "n0", "n3", min_confidence=None)
        assert r is not None

    def test_min_confidence_edges_without_hd_not_excluded(self):
        """Edges without hd_refinement.confidence are never excluded by min_confidence."""
        # No confidence data set.
        g = _make_4node_graph()
        r = shortest_path(g, "n0", "n3", min_confidence=0.99)
        assert r is not None

    def test_min_confidence_with_prefer_observed_combined(self):
        """Both hooks can be combined: exclude low-confidence, prefer observed."""
        g = _make_4node_graph(path_a_confidence=0.3, path_b_confidence=0.8)
        # min_confidence=0.5 → Path A excluded → Path B (unobserved but ok) used.
        r = shortest_path(
            g, "n0", "n3",
            prefer_observed=True,
            min_confidence=0.5,
        )
        assert set(r.edge_sequence) == {"e02", "e23"}


# ---------------------------------------------------------------------------
# Tests: regression — default call produces same Route as 0.5.0
# ---------------------------------------------------------------------------


class TestRegressionDefaultCall:
    def test_regression_same_graph_same_route(self):
        """Calling shortest_path without any 0.6.0 flags must give same result."""
        g = Graph(
            nodes=[
                Node("a", (0.0, 0.0)),
                Node("b", (30.0, 0.0)),
                Node("c", (60.0, 0.0)),
            ],
            edges=[
                Edge("e1", "a", "b", [(0.0, 0.0), (30.0, 0.0)]),
                Edge("e2", "b", "c", [(30.0, 0.0), (60.0, 0.0)]),
            ],
        )
        r = shortest_path(g, "a", "c")
        assert r.node_sequence == ["a", "b", "c"]
        assert r.edge_sequence == ["e1", "e2"]
        assert math.isclose(r.total_length_m, 60.0)
