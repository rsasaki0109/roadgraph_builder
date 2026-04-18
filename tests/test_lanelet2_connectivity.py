from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
from roadgraph_builder.io.export.lanelet2 import export_lanelet2


def _t_junction_graph():
    g = Graph(
        nodes=[
            Node(id="j", position=(0.0, 0.0), attributes={"junction_hint": "multi_branch", "junction_type": "t_junction", "degree": 3}),
            Node(id="w", position=(-50.0, 0.0), attributes={"junction_hint": "dead_end", "degree": 1}),
            Node(id="e", position=(50.0, 0.0), attributes={"junction_hint": "dead_end", "degree": 1}),
            Node(id="s", position=(0.0, -30.0), attributes={"junction_hint": "dead_end", "degree": 1}),
        ],
        edges=[
            Edge(id="eW", start_node_id="w", end_node_id="j", polyline=[(-50.0, 0.0), (0.0, 0.0)], attributes={}),
            Edge(id="eE", start_node_id="j", end_node_id="e", polyline=[(0.0, 0.0), (50.0, 0.0)], attributes={}),
            Edge(id="eS", start_node_id="j", end_node_id="s", polyline=[(0.0, 0.0), (0.0, -30.0)], attributes={}),
        ],
    )
    enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=3.0))
    return g


def test_lanelet2_emits_lane_connection_relation_at_junction(tmp_path: Path):
    g = _t_junction_graph()
    out = tmp_path / "lane.osm"
    export_lanelet2(g, out, origin_lat=52.52, origin_lon=13.405)
    tree = ET.parse(out)
    root = tree.getroot()

    # Every non-self-loop edge with both boundaries becomes a lanelet.
    lanelet_relations = [
        r
        for r in root.findall("relation")
        if any(t.get("k") == "type" and t.get("v") == "lanelet" for t in r.findall("tag"))
    ]
    assert len(lanelet_relations) == 3

    # Exactly one lane_connection relation per junction node that has ≥2
    # incident lanelets; with this graph that's node "j" only.
    connections = [
        r
        for r in root.findall("relation")
        if any(t.get("k") == "roadgraph" and t.get("v") == "lane_connection" for t in r.findall("tag"))
    ]
    assert len(connections) == 1
    conn = connections[0]
    # Junction node id tag present.
    tags = {t.get("k"): t.get("v") for t in conn.findall("tag")}
    assert tags["type"] == "regulatory_element"
    assert tags["subtype"] == "lane_connection"
    assert tags["roadgraph:junction_node_id"] == "j"
    assert tags["roadgraph:junction_type"] == "t_junction"
    assert tags["roadgraph:junction_hint"] == "multi_branch"
    # Three lanelet members (one per incident edge).
    members = conn.findall("member")
    assert len(members) == 3
    assert all(m.get("type") == "relation" for m in members)
    roles = {m.get("role") for m in members}
    assert roles <= {"from_start", "from_end"}


def test_lanelet2_emits_no_connection_when_node_has_one_lanelet(tmp_path: Path):
    # Single edge between two dead ends → no junction has two lanelets.
    g = Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0), attributes={"junction_hint": "dead_end"}),
            Node(id="b", position=(50.0, 0.0), attributes={"junction_hint": "dead_end"}),
        ],
        edges=[
            Edge(id="e", start_node_id="a", end_node_id="b", polyline=[(0.0, 0.0), (50.0, 0.0)], attributes={}),
        ],
    )
    enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=2.0))
    out = tmp_path / "single.osm"
    export_lanelet2(g, out, origin_lat=52.52, origin_lon=13.405)
    tree = ET.parse(out)
    root = tree.getroot()
    connections = [
        r
        for r in root.findall("relation")
        if any(t.get("k") == "roadgraph" and t.get("v") == "lane_connection" for t in r.findall("tag"))
    ]
    assert connections == []
