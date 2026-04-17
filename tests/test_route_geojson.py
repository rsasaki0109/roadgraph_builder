from __future__ import annotations

import json
from pathlib import Path

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.routing.geojson_export import build_route_geojson, write_route_geojson
from roadgraph_builder.routing.shortest_path import shortest_path


def _linear_graph():
    nodes = [
        Node(id="a", position=(0.0, 0.0)),
        Node(id="b", position=(30.0, 0.0)),
        Node(id="c", position=(60.0, 0.0)),
    ]
    edges = [
        Edge(
            id="e1",
            start_node_id="a",
            end_node_id="b",
            polyline=[(0.0, 0.0), (15.0, 0.0), (30.0, 0.0)],
        ),
        Edge(
            id="e2",
            start_node_id="b",
            end_node_id="c",
            polyline=[(30.0, 0.0), (45.0, 0.0), (60.0, 0.0)],
        ),
    ]
    return Graph(nodes=nodes, edges=edges)


def test_build_route_geojson_forward():
    g = _linear_graph()
    route = shortest_path(g, "a", "c")
    fc = build_route_geojson(g, route, origin_lat=52.52, origin_lon=13.405)
    assert fc["type"] == "FeatureCollection"
    kinds = [f["properties"]["kind"] for f in fc["features"]]
    assert kinds.count("route") == 1
    assert kinds.count("route_edge") == 2
    assert kinds.count("route_start") == 1
    assert kinds.count("route_end") == 1

    merged = next(f for f in fc["features"] if f["properties"]["kind"] == "route")
    coords = merged["geometry"]["coordinates"]
    # 3 vertices for e1 + 2 more (skipping shared junction vertex) for e2 = 5.
    assert len(coords) == 5
    # First coordinate corresponds to (0, 0) meters = origin in WGS84.
    assert coords[0] == [13.405, 52.52]


def test_build_route_geojson_reverses_reverse_direction():
    g = _linear_graph()
    # Traverse a→c then from c back to a; the Dijkstra will pick reverse over same edges.
    route = shortest_path(g, "c", "a")
    fc = build_route_geojson(g, route, origin_lat=52.52, origin_lon=13.405)
    edges = [f for f in fc["features"] if f["properties"]["kind"] == "route_edge"]
    # Each edge should report direction=reverse, and the edge's coords should start
    # at that edge's end_node position (c for e2, b for e1).
    assert edges[0]["properties"]["direction"] == "reverse"
    first_edge_first_xy_lon = edges[0]["geometry"]["coordinates"][0][0]
    # Reverse traversal of e2 starts from (60, 0) meters → lon > origin lon.
    assert first_edge_first_xy_lon > 13.405


def test_write_route_geojson_round_trips(tmp_path: Path):
    g = _linear_graph()
    route = shortest_path(g, "a", "c")
    out = tmp_path / "route.geojson"
    write_route_geojson(out, g, route, origin_lat=52.52, origin_lon=13.405)
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["properties"]["total_length_m"] == pytest.approx(60.0)
    assert doc["properties"]["edge_count"] == 2


def test_route_cli_writes_geojson(tmp_path: Path, capsys):
    from roadgraph_builder.cli.main import main
    from roadgraph_builder.io.export.json_exporter import export_graph_json

    g = _linear_graph()
    g.metadata["map_origin"] = {"lat0": 52.52, "lon0": 13.405}
    graph_json = tmp_path / "g.json"
    export_graph_json(g, graph_json)

    out_gj = tmp_path / "route.geojson"
    rc = main(["route", str(graph_json), "a", "c", "--output", str(out_gj)])
    assert rc == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["output"] == str(out_gj)
    doc = json.loads(out_gj.read_text(encoding="utf-8"))
    assert doc["type"] == "FeatureCollection"
    assert doc["properties"]["edge_count"] == 2


def test_route_cli_output_requires_origin(tmp_path: Path, capsys):
    from roadgraph_builder.cli.main import main
    from roadgraph_builder.io.export.json_exporter import export_graph_json

    g = _linear_graph()  # No metadata.map_origin on purpose.
    graph_json = tmp_path / "g.json"
    export_graph_json(g, graph_json)

    out_gj = tmp_path / "route.geojson"
    rc = main(["route", str(graph_json), "a", "c", "--output", str(out_gj)])
    assert rc == 1
    assert "origin" in capsys.readouterr().err
    assert not out_gj.exists()
