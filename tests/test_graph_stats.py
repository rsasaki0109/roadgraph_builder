from __future__ import annotations

import json
from pathlib import Path

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.core.graph.stats import graph_stats, junction_stats


def _sample_graph():
    nodes = [
        Node(id="a", position=(0.0, 0.0), attributes={"junction_hint": "dead_end", "degree": 1}),
        Node(id="b", position=(30.0, 0.0), attributes={
            "junction_hint": "multi_branch",
            "junction_type": "t_junction",
            "degree": 3,
        }),
        Node(id="c", position=(60.0, 0.0), attributes={"junction_hint": "dead_end", "degree": 1}),
        Node(id="d", position=(30.0, 40.0), attributes={"junction_hint": "dead_end", "degree": 1}),
    ]
    edges = [
        Edge(id="e1", start_node_id="a", end_node_id="b", polyline=[(0, 0), (30, 0)]),
        Edge(id="e2", start_node_id="b", end_node_id="c", polyline=[(30, 0), (60, 0)]),
        Edge(id="e3", start_node_id="b", end_node_id="d", polyline=[(30, 0), (30, 40)]),
    ]
    return Graph(nodes=nodes, edges=edges)


def test_graph_stats_without_origin_omits_wgs84():
    g = _sample_graph()
    s = graph_stats(g)
    assert s["edge_count"] == 3
    assert s["node_count"] == 4
    assert s["edge_length"]["min_m"] == 30.0
    assert s["edge_length"]["max_m"] == 40.0
    assert s["edge_length"]["total_m"] == 100.0
    assert s["bbox_m"] == {"x_min_m": 0.0, "y_min_m": 0.0, "x_max_m": 60.0, "y_max_m": 40.0}
    assert "bbox_wgs84_deg" not in s


def test_graph_stats_reads_origin_from_metadata():
    g = _sample_graph()
    g.metadata["map_origin"] = {"lat0": 52.52, "lon0": 13.405}
    s = graph_stats(g)
    assert "bbox_wgs84_deg" in s
    assert s["bbox_wgs84_deg"]["sw_lon"] == 13.405


def test_graph_stats_explicit_origin_beats_metadata():
    g = _sample_graph()
    g.metadata["map_origin"] = {"lat0": 52.52, "lon0": 13.405}
    s = graph_stats(g, origin_lat=48.857, origin_lon=2.347)
    assert "bbox_wgs84_deg" in s
    assert s["bbox_wgs84_deg"]["sw_lon"] == 2.347


def test_junction_stats_counts_hints_and_types():
    g = _sample_graph()
    j = junction_stats(g)
    assert j["total_nodes"] == 4
    assert j["hints"] == {"dead_end": 3, "multi_branch": 1}
    assert j["multi_branch_types"] == {"t_junction": 1}


def test_stats_cli_prints_json(tmp_path: Path, capsys):
    from roadgraph_builder.cli.main import main
    from roadgraph_builder.io.export.json_exporter import export_graph_json

    out = tmp_path / "g.json"
    export_graph_json(_sample_graph(), out)
    assert main(["stats", str(out)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["graph_stats"]["edge_count"] == 3
    assert doc["junctions"]["hints"]["multi_branch"] == 1
    assert doc["junctions"]["multi_branch_types"]["t_junction"] == 1
