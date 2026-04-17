from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.routing.shortest_path import shortest_path


def _straight_polyline(p0: tuple[float, float], p1: tuple[float, float], steps: int = 2):
    return [
        (p0[0] + (p1[0] - p0[0]) * i / (steps - 1), p0[1] + (p1[1] - p0[1]) * i / (steps - 1))
        for i in range(steps)
    ]


def _manual_graph():
    nodes = [
        Node(id="a", position=(0.0, 0.0)),
        Node(id="b", position=(30.0, 0.0)),
        Node(id="c", position=(60.0, 0.0)),
        Node(id="d", position=(30.0, 40.0)),
    ]
    edges = [
        Edge(id="e1", start_node_id="a", end_node_id="b", polyline=_straight_polyline((0, 0), (30, 0))),
        Edge(id="e2", start_node_id="b", end_node_id="c", polyline=_straight_polyline((30, 0), (60, 0))),
        Edge(id="e3", start_node_id="b", end_node_id="d", polyline=_straight_polyline((30, 0), (30, 40))),
    ]
    return Graph(nodes=nodes, edges=edges)


def test_shortest_path_linear():
    g = _manual_graph()
    r = shortest_path(g, "a", "c")
    assert r.node_sequence == ["a", "b", "c"]
    assert r.edge_sequence == ["e1", "e2"]
    assert math.isclose(r.total_length_m, 60.0)


def test_shortest_path_same_node_is_empty():
    g = _manual_graph()
    r = shortest_path(g, "a", "a")
    assert r.node_sequence == ["a"]
    assert r.edge_sequence == []
    assert r.total_length_m == 0.0


def test_shortest_path_prefers_shorter_branch():
    # Two alternate routes from a to c: a-b-c (60 m) vs a-b-d (40 m detour, dead end)
    # so we also add direct a-c shortcut of 90 m to verify tie-break isn't on count.
    g = _manual_graph()
    g = Graph(
        nodes=g.nodes,
        edges=g.edges
        + [
            Edge(
                id="e4",
                start_node_id="a",
                end_node_id="c",
                polyline=_straight_polyline((0, 0), (90, 0)),
            )
        ],
    )
    r = shortest_path(g, "a", "c")
    # 60 m (via b) beats the direct 90 m shortcut.
    assert r.edge_sequence == ["e1", "e2"]
    assert math.isclose(r.total_length_m, 60.0)


def test_shortest_path_disjoint_raises():
    g = _manual_graph()
    g = Graph(
        nodes=g.nodes + [Node(id="z", position=(500.0, 500.0))],
        edges=g.edges,
    )
    with pytest.raises(ValueError, match="no path"):
        shortest_path(g, "a", "z")


def test_shortest_path_unknown_node_raises():
    g = _manual_graph()
    with pytest.raises(KeyError):
        shortest_path(g, "a", "missing")


def test_route_cli_prints_json(tmp_path: Path, capsys):
    from roadgraph_builder.cli.main import main
    from roadgraph_builder.io.export.json_exporter import export_graph_json

    g = _manual_graph()
    out = tmp_path / "g.json"
    export_graph_json(g, out)

    rc = main(["route", str(out), "a", "c"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["from_node"] == "a"
    assert doc["to_node"] == "c"
    assert doc["edge_sequence"] == ["e1", "e2"]
    assert math.isclose(doc["total_length_m"], 60.0)


def test_route_cli_rejects_unknown_node(tmp_path: Path, capsys):
    from roadgraph_builder.cli.main import main
    from roadgraph_builder.io.export.json_exporter import export_graph_json

    out = tmp_path / "g.json"
    export_graph_json(_manual_graph(), out)
    rc = main(["route", str(out), "a", "nope"])
    assert rc == 1
    assert "nope" in capsys.readouterr().err
