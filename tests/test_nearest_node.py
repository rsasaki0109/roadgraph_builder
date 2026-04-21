from __future__ import annotations

import json
from pathlib import Path

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.routing.nearest import nearest_node


def _three_node_graph():
    return Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0)),
            Node(id="b", position=(30.0, 0.0)),
            Node(id="c", position=(60.0, 0.0)),
        ],
        edges=[
            Edge(id="e1", start_node_id="a", end_node_id="b", polyline=[(0.0, 0.0), (30.0, 0.0)]),
            Edge(id="e2", start_node_id="b", end_node_id="c", polyline=[(30.0, 0.0), (60.0, 0.0)]),
        ],
    )


def test_nearest_node_by_xy_picks_closest():
    g = _three_node_graph()
    r = nearest_node(g, x_m=28.0, y_m=0.5)
    assert r.node_id == "b"
    assert r.distance_m < 3.0


def test_nearest_node_cached_index_tracks_appended_nodes():
    g = _three_node_graph()
    assert nearest_node(g, x_m=100.0, y_m=0.0).node_id == "c"

    g.nodes.append(Node(id="d", position=(100.0, 0.0)))
    r = nearest_node(g, x_m=100.0, y_m=0.0)
    assert r.node_id == "d"
    assert r.distance_m == 0.0


def test_nearest_node_cached_index_tracks_endpoint_position_replacement():
    g = _three_node_graph()
    assert nearest_node(g, x_m=-20.0, y_m=0.0).node_id == "a"

    g.nodes[0].position = (-20.0, 0.0)
    r = nearest_node(g, x_m=-20.0, y_m=0.0)
    assert r.node_id == "a"
    assert r.distance_m == 0.0


def test_nearest_node_matches_bruteforce_on_scattered_points():
    nodes = [
        Node(id=f"n{i}", position=(float((i * 37) % 113), float((i * 19) % 89)))
        for i in range(30)
    ]
    g = Graph(nodes=nodes, edges=[])
    for i in range(50):
        x = float((i * 11) % 130) - 8.25
        y = float((i * 17) % 100) - 5.75
        r = nearest_node(g, x_m=x, y_m=y)
        expected = min(
            nodes,
            key=lambda n: (float(n.position[0] - x) ** 2 + float(n.position[1] - y) ** 2),
        )
        assert r.node_id == expected.id


def test_nearest_node_far_outside_graph_extent():
    g = _three_node_graph()
    r = nearest_node(g, x_m=10_000.0, y_m=0.0)
    assert r.node_id == "c"


def test_nearest_node_by_latlon_uses_metadata_origin():
    g = _three_node_graph()
    g.metadata["map_origin"] = {"lat0": 52.52, "lon0": 13.405}
    # Coordinate close to node "a" (the origin in WGS84).
    r = nearest_node(g, lat=52.52, lon=13.405)
    assert r.node_id == "a"
    assert r.distance_m < 0.01


def test_nearest_node_rejects_both_or_neither():
    g = _three_node_graph()
    with pytest.raises(ValueError):
        nearest_node(g)
    with pytest.raises(ValueError):
        nearest_node(g, x_m=0.0, y_m=0.0, lat=52.52, lon=13.405)


def test_nearest_node_requires_origin_for_latlon():
    g = _three_node_graph()
    with pytest.raises(ValueError, match="origin"):
        nearest_node(g, lat=52.52, lon=13.405)


def test_nearest_node_cli_xy(tmp_path: Path, capsys):
    from roadgraph_builder.cli.main import main
    from roadgraph_builder.io.export.json_exporter import export_graph_json

    out = tmp_path / "g.json"
    export_graph_json(_three_node_graph(), out)
    rc = main(["nearest-node", str(out), "--xy", "55.0", "0.0"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["node_id"] == "c"
    assert doc["distance_m"] < 6.0


def test_route_cli_accepts_latlon(tmp_path: Path, capsys):
    from roadgraph_builder.cli.main import main
    from roadgraph_builder.io.export.json_exporter import export_graph_json

    g = _three_node_graph()
    g.metadata["map_origin"] = {"lat0": 52.52, "lon0": 13.405}
    out = tmp_path / "g.json"
    export_graph_json(g, out)
    rc = main(
        [
            "route",
            str(out),
            "--from-latlon",
            "52.52",
            "13.405",
            "--to-latlon",
            "52.52",
            "13.40554",
        ]
    )
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["from_node"] == "a"
    # 0.00054 deg lon at this latitude ~ 36 m — should snap to node b (30 m)
    assert doc["to_node"] in {"b", "c"}
    assert doc["snapped_from"]["requested_lat"] == 52.52
    assert doc["snapped_to"] is not None
