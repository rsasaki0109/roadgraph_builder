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
    assert r.edge_directions == ["forward", "forward"]
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


def test_shortest_path_cached_index_tracks_appended_edges():
    g = _manual_graph()
    assert shortest_path(g, "a", "c").edge_sequence == ["e1", "e2"]

    g.edges.append(
        Edge(
            id="shortcut",
            start_node_id="a",
            end_node_id="c",
            polyline=_straight_polyline((0, 0), (10, 0)),
        )
    )
    r = shortest_path(g, "a", "c")
    assert r.edge_sequence == ["shortcut"]
    assert math.isclose(r.total_length_m, 10.0)


def test_shortest_path_cached_index_tracks_replaced_polyline():
    g = _manual_graph()
    shortcut = Edge(
        id="shortcut",
        start_node_id="a",
        end_node_id="c",
        polyline=_straight_polyline((0, 0), (90, 0)),
    )
    g.edges.append(shortcut)
    assert shortest_path(g, "a", "c").edge_sequence == ["e1", "e2"]

    shortcut.polyline = _straight_polyline((0, 0), (10, 0))
    r = shortest_path(g, "a", "c")
    assert r.edge_sequence == ["shortcut"]
    assert math.isclose(r.total_length_m, 10.0)


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


def _two_route_graph():
    """a—b—c direct (60 m) plus a—b—d—c detour (40+40+40=120 m via d-c link)."""
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
        Edge(id="e4", start_node_id="d", end_node_id="c", polyline=_straight_polyline((30, 40), (60, 0))),
    ]
    return Graph(nodes=nodes, edges=edges)


def test_no_turn_forces_detour():
    """Forbidding e1-forward → e2-forward at b should reroute through d."""
    g = _two_route_graph()
    restrictions = [
        {
            "junction_node_id": "b",
            "from_edge_id": "e1",
            "from_direction": "forward",
            "to_edge_id": "e2",
            "to_direction": "forward",
            "restriction": "no_left_turn",
        }
    ]
    r = shortest_path(g, "a", "c", turn_restrictions=restrictions)
    assert r.edge_sequence == ["e1", "e3", "e4"]
    # a-b-d detour should go through d, not e2.
    assert "e2" not in r.edge_sequence


def test_only_turn_whitelists_single_branch():
    """only_straight at b with (e1→e2) allowed should NOT take the detour branch."""
    g = _two_route_graph()
    restrictions = [
        {
            "junction_node_id": "b",
            "from_edge_id": "e1",
            "from_direction": "forward",
            "to_edge_id": "e2",
            "to_direction": "forward",
            "restriction": "only_straight",
        }
    ]
    r = shortest_path(g, "a", "c", turn_restrictions=restrictions)
    assert r.edge_sequence == ["e1", "e2"]
    # Also verify only_* forbids the detour branch at b.
    restrictions_force_detour = [
        {
            "junction_node_id": "b",
            "from_edge_id": "e1",
            "from_direction": "forward",
            "to_edge_id": "e3",
            "to_direction": "forward",
            "restriction": "only_left",
        }
    ]
    r2 = shortest_path(g, "a", "c", turn_restrictions=restrictions_force_detour)
    assert r2.edge_sequence == ["e1", "e3", "e4"]


def test_no_turn_unsatisfiable_raises():
    g = _two_route_graph()
    # Block both ways out of b after e1: direct AND the detour branch.
    restrictions = [
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
            "from_edge_id": "e1",
            "from_direction": "forward",
            "to_edge_id": "e3",
            "to_direction": "forward",
            "restriction": "no_left_turn",
        },
    ]
    with pytest.raises(ValueError, match="no path"):
        shortest_path(g, "a", "c", turn_restrictions=restrictions)


def test_route_cli_reads_turn_restrictions_from_sd_nav(tmp_path: Path, capsys):
    from roadgraph_builder.cli.main import main
    from roadgraph_builder.io.export.json_exporter import export_graph_json

    g = _two_route_graph()
    graph_json = tmp_path / "g.json"
    export_graph_json(g, graph_json)
    sd_nav = tmp_path / "sd_nav.json"
    sd_nav.write_text(
        json.dumps(
            {
                "turn_restrictions": [
                    {
                        "id": "tr_0",
                        "junction_node_id": "b",
                        "from_edge_id": "e1",
                        "from_direction": "forward",
                        "to_edge_id": "e2",
                        "to_direction": "forward",
                        "restriction": "no_left_turn",
                        "source": "manual",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "route",
            str(graph_json),
            "a",
            "c",
            "--turn-restrictions-json",
            str(sd_nav),
        ]
    )
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["applied_restrictions"] == 1
    assert doc["edge_sequence"] == ["e1", "e3", "e4"]
