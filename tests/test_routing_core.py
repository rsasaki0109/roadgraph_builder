from __future__ import annotations

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.routing._core import (
    RoutingCostOptions,
    build_weighted_adjacency,
    get_routing_index,
    parse_turn_policy,
)


def _core_graph() -> Graph:
    observed_attrs = {
        "trace_stats": {"trace_observation_count": 3},
        "hd": {"hd_refinement": {"confidence": 0.9}},
        "slope_deg": 5.0,
    }
    low_conf_attrs = {"hd": {"hd_refinement": {"confidence": 0.2}}}
    return Graph(
        nodes=[
            Node("a", (0.0, 0.0)),
            Node("b", (10.0, 0.0)),
            Node("c", (20.0, 0.0)),
        ],
        edges=[
            Edge("e1", "a", "b", [(0.0, 0.0), (10.0, 0.0)], attributes=observed_attrs),
            Edge("e2", "b", "c", [(10.0, 0.0), (20.0, 0.0)], attributes=low_conf_attrs),
        ],
    )


def test_turn_policy_combines_forbidden_and_only_restrictions():
    policy = parse_turn_policy(
        [
            {
                "junction_node_id": "b",
                "from_edge_id": "e1",
                "from_direction": "forward",
                "to_edge_id": "e2",
                "to_direction": "forward",
                "restriction": "no_straight",
            },
            {
                "junction_node_id": "b",
                "from_edge_id": "e3",
                "from_direction": "reverse",
                "to_edge_id": "e4",
                "to_direction": "forward",
                "restriction": "only_right",
            },
        ]
    )

    assert not policy.is_empty
    assert not policy.allows_transition("b", "e1", "forward", "e2", "forward")
    assert policy.allows_transition("b", "e1", "forward", "e5", "reverse")
    assert policy.allows_transition("b", "e3", "reverse", "e4", "forward")
    assert not policy.allows_transition("b", "e3", "reverse", "e5", "forward")
    assert policy.allows_transition("b", None, None, "e2", "forward")


def test_weighted_adjacency_reuses_base_adjacency_for_default_costs():
    graph = _core_graph()
    index = get_routing_index(graph)

    assert build_weighted_adjacency(graph, index, RoutingCostOptions()) is index.base_adj


def test_routing_index_tracks_node_position_mutation():
    graph = _core_graph()
    index = get_routing_index(graph)

    graph.nodes[1].position = (10.0, 5.0)
    updated = get_routing_index(graph)

    assert updated is not index
    assert updated.node_positions["b"] == (10.0, 5.0)


def test_routing_index_tracks_two_point_polyline_mutation():
    graph = _core_graph()
    index = get_routing_index(graph)

    graph.edges[0].polyline[1] = (12.0, 0.0)
    updated = get_routing_index(graph)

    assert updated is not index
    assert updated.base_lengths["e1"] == pytest.approx(12.0)


def test_cost_options_report_when_straight_line_heuristic_is_safe():
    assert RoutingCostOptions().preserves_base_metric_lower_bound
    assert RoutingCostOptions(min_confidence=0.5).preserves_base_metric_lower_bound
    assert RoutingCostOptions(
        prefer_observed=True,
        observed_bonus=1.0,
        unobserved_penalty=2.0,
    ).preserves_base_metric_lower_bound
    assert not RoutingCostOptions(
        prefer_observed=True,
        observed_bonus=0.5,
        unobserved_penalty=2.0,
    ).preserves_base_metric_lower_bound
    assert not RoutingCostOptions(downhill_bonus=0.5).preserves_base_metric_lower_bound
    assert not RoutingCostOptions(uphill_penalty=0.5).preserves_base_metric_lower_bound


def test_weighted_adjacency_applies_cost_hooks_and_filters_confidence():
    graph = _core_graph()
    index = get_routing_index(graph)
    adj = build_weighted_adjacency(
        graph,
        index,
        RoutingCostOptions(
            prefer_observed=True,
            observed_bonus=0.5,
            unobserved_penalty=2.0,
            min_confidence=0.5,
            uphill_penalty=2.0,
            downhill_bonus=0.25,
        ),
    )

    assert adj["a"][0][:3] == ("e1", "forward", "b")
    assert adj["a"][0][3] == pytest.approx(10.0)
    assert adj["b"][0][:3] == ("e1", "reverse", "a")
    assert adj["b"][0][3] == pytest.approx(1.25)
    assert adj["c"] == []
