from __future__ import annotations

import math

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.routing.reachability import ReachabilityAnalyzer, reachable_within


def _line(p0: tuple[float, float], p1: tuple[float, float]) -> list[tuple[float, float]]:
    return [p0, p1]


def _branch_graph() -> Graph:
    return Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0)),
            Node(id="b", position=(30.0, 0.0)),
            Node(id="c", position=(60.0, 0.0)),
            Node(id="d", position=(30.0, 40.0)),
        ],
        edges=[
            Edge(id="e1", start_node_id="a", end_node_id="b", polyline=_line((0, 0), (30, 0))),
            Edge(id="e2", start_node_id="b", end_node_id="c", polyline=_line((30, 0), (60, 0))),
            Edge(id="e3", start_node_id="b", end_node_id="d", polyline=_line((30, 0), (30, 40))),
        ],
    )


def test_reachable_within_returns_nodes_and_partial_edge_spans():
    result = reachable_within(_branch_graph(), "a", max_cost_m=35.0)

    node_costs = {n.node_id: n.cost_m for n in result.nodes}
    assert node_costs == {"a": 0.0, "b": 30.0}

    spans = {(e.edge_id, e.direction): e for e in result.edges}
    assert spans[("e1", "forward")].complete is True
    assert spans[("e2", "forward")].complete is False
    assert spans[("e2", "forward")].reachable_fraction == pytest.approx(5.0 / 30.0)
    assert spans[("e3", "forward")].reachable_fraction == pytest.approx(5.0 / 40.0)


def test_reachable_within_respects_turn_restrictions():
    restrictions = [
        {
            "junction_node_id": "b",
            "from_edge_id": "e1",
            "from_direction": "forward",
            "to_edge_id": "e2",
            "to_direction": "forward",
            "restriction": "no_straight",
        }
    ]

    result = reachable_within(
        _branch_graph(),
        "a",
        max_cost_m=80.0,
        turn_restrictions=restrictions,
    )

    spans = {(e.edge_id, e.direction): e for e in result.edges}
    assert ("e2", "forward") not in spans
    assert spans[("e3", "forward")].complete is True
    assert {n.node_id for n in result.nodes} == {"a", "b", "d"}


def test_reachable_unrestricted_fast_path_matches_state_search():
    graph = _branch_graph()
    no_restrictions = reachable_within(graph, "a", max_cost_m=80.0)
    irrelevant_restriction = [
        {
            "junction_node_id": "missing",
            "from_edge_id": "missing_from",
            "from_direction": "forward",
            "to_edge_id": "missing_to",
            "to_direction": "forward",
            "restriction": "no_straight",
        }
    ]
    state_search = reachable_within(
        graph,
        "a",
        max_cost_m=80.0,
        turn_restrictions=irrelevant_restriction,
    )

    assert no_restrictions == state_search


def test_reachability_analyzer_reuses_policy_for_many_queries():
    graph = _branch_graph()
    restrictions = [
        {
            "junction_node_id": "b",
            "from_edge_id": "e1",
            "from_direction": "forward",
            "to_edge_id": "e2",
            "to_direction": "forward",
            "restriction": "no_straight",
        }
    ]
    analyzer = ReachabilityAnalyzer(graph, turn_restrictions=restrictions)

    assert analyzer.reachable_within("a", max_cost_m=80.0) == reachable_within(
        graph,
        "a",
        max_cost_m=80.0,
        turn_restrictions=restrictions,
    )
    assert {n.node_id for n in analyzer.reachable_within("b", max_cost_m=30.0).nodes} == {
        "a",
        "b",
        "c",
    }


def test_reachable_within_uses_confidence_filter_and_unknown_node_errors():
    graph = _branch_graph()
    graph.edges[0].attributes["hd"] = {"hd_refinement": {"confidence": 0.2}}

    result = reachable_within(graph, "a", max_cost_m=100.0, min_confidence=0.9)
    assert [n.node_id for n in result.nodes] == ["a"]
    assert result.edges == []

    with pytest.raises(KeyError):
        reachable_within(graph, "missing", max_cost_m=10.0)
    with pytest.raises(ValueError, match="non-negative"):
        reachable_within(graph, "a", max_cost_m=-1.0)


def test_reachable_within_cache_tracks_mutated_polyline_lengths():
    graph = _branch_graph()
    first = reachable_within(graph, "a", max_cost_m=35.0)
    assert any(e.edge_id == "e2" and not e.complete for e in first.edges)

    graph.edges[0].polyline[1] = (100.0, 0.0)
    second = reachable_within(graph, "a", max_cost_m=35.0)
    spans = {(e.edge_id, e.direction): e for e in second.edges}
    assert {n.node_id for n in second.nodes} == {"a"}
    assert spans[("e1", "forward")].complete is False
    assert math.isclose(spans[("e1", "forward")].reachable_fraction, 0.35)
