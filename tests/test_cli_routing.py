from __future__ import annotations

import argparse
import io
import json

import pytest

from roadgraph_builder.cli.routing import (
    CliRoutingError,
    resolve_route_endpoint,
    resolve_route_origin,
    run_nearest_node,
    run_route,
    turn_restrictions_from_document,
)
from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node


def _line_graph() -> Graph:
    return Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0)),
            Node(id="b", position=(30.0, 0.0)),
        ],
        edges=[
            Edge(
                id="e1",
                start_node_id="a",
                end_node_id="b",
                polyline=[(0.0, 0.0), (30.0, 0.0)],
            )
        ],
        metadata={"map_origin": {"lat0": 52.52, "lon0": 13.405}},
    )


def _route_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "input_json": "graph.json",
        "from_node": "a",
        "to_node": "b",
        "from_latlon": None,
        "to_latlon": None,
        "turn_restrictions_json": None,
        "output": None,
        "origin_lat": None,
        "origin_lon": None,
        "prefer_observed": False,
        "min_confidence": None,
        "observed_bonus": 0.5,
        "unobserved_penalty": 2.0,
        "uphill_penalty": None,
        "downhill_bonus": None,
        "allow_lane_change": False,
        "lane_change_cost_m": 50.0,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_turn_restrictions_from_document_filters_supported_shapes():
    restriction = {"junction_node_id": "b", "from_edge_id": "e1"}

    assert turn_restrictions_from_document({"turn_restrictions": [restriction, "bad"]}) == [restriction]
    assert turn_restrictions_from_document([restriction, 3, None]) == [restriction]
    assert turn_restrictions_from_document({"turn_restrictions": "bad"}) == []
    assert turn_restrictions_from_document("bad") == []


def test_resolve_route_endpoint_snaps_latlon_with_metadata_origin():
    endpoint = resolve_route_endpoint(
        _line_graph(),
        label="from",
        latlon=(52.52, 13.405),
        positional=None,
        origin_lat=None,
        origin_lon=None,
        graph_label="graph.json",
    )

    assert endpoint.node_id == "a"
    assert endpoint.snap is not None
    assert endpoint.snap["requested_lat"] == 52.52
    assert endpoint.snap["distance_m"] < 0.01


def test_resolve_route_endpoint_rejects_ambiguous_input():
    with pytest.raises(CliRoutingError, match="either a node id"):
        resolve_route_endpoint(
            _line_graph(),
            label="from",
            latlon=(52.52, 13.405),
            positional="a",
            origin_lat=None,
            origin_lon=None,
            graph_label="graph.json",
        )


def test_resolve_route_origin_prefers_explicit_pair_and_validates_partial_pair():
    graph = _line_graph()

    assert resolve_route_origin(graph, origin_lat=1.0, origin_lon=2.0) == (1.0, 2.0)
    assert resolve_route_origin(graph, origin_lat=None, origin_lon=None) == (52.52, 13.405)
    with pytest.raises(CliRoutingError, match="pass both"):
        resolve_route_origin(graph, origin_lat=1.0, origin_lon=None)


def test_run_nearest_node_isolated_from_file_io():
    stdout = io.StringIO()
    args = argparse.Namespace(
        input_json="graph.json",
        xy=(29.0, 0.0),
        latlon=None,
        origin_lat=None,
        origin_lon=None,
    )

    rc = run_nearest_node(args, load_graph=lambda _path: _line_graph(), stdout=stdout)

    assert rc == 0
    doc = json.loads(stdout.getvalue())
    assert doc["node_id"] == "b"
    assert doc["distance_m"] == 1.0


def test_run_route_isolated_from_file_io_and_parser():
    stdout = io.StringIO()

    rc = run_route(
        _route_args(),
        load_graph=lambda _path: _line_graph(),
        load_json=lambda _path: {},
        stdout=stdout,
    )

    assert rc == 0
    doc = json.loads(stdout.getvalue())
    assert doc["from_node"] == "a"
    assert doc["to_node"] == "b"
    assert doc["edge_sequence"] == ["e1"]
    assert doc["applied_restrictions"] == 0


def test_run_route_reports_both_missing_endpoints():
    stderr = io.StringIO()

    rc = run_route(
        _route_args(from_node=None, to_node=None),
        load_graph=lambda _path: _line_graph(),
        load_json=lambda _path: {},
        stderr=stderr,
    )

    assert rc == 1
    err = stderr.getvalue()
    assert "from_node positional" in err
    assert "to_node positional" in err
