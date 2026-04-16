from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
from roadgraph_builder.io.export.lanelet2 import export_lanelet2


def test_export_lanelet2_writes_osm(tmp_path: Path):
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n0",
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                attributes={},
            )
        ],
    )
    enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=3.5))
    out = tmp_path / "out.osm"
    export_lanelet2(g, out, origin_lat=52.5, origin_lon=13.4)
    tree = ET.parse(out)
    root = tree.getroot()
    assert root.tag == "osm"
    nodes = [el for el in root if el.tag == "node"]
    ways = [el for el in root if el.tag == "way"]
    relations = [el for el in root if el.tag == "relation"]
    assert len(nodes) >= 4
    assert len(ways) >= 3
    assert len(relations) >= 1
    kind_tags = [el.get("v") for r in relations for el in r if el.tag == "tag" and el.get("k") == "type"]
    assert "lanelet" in kind_tags
    center_members = [
        m.get("role")
        for r in relations
        for m in r
        if m.tag == "member" and m.get("type") == "way" and m.get("role") == "centerline"
    ]
    assert len(center_members) >= 1


def test_export_empty_graph(tmp_path: Path):
    g = Graph()
    out = tmp_path / "e.osm"
    export_lanelet2(g, out, origin_lat=0.0, origin_lon=0.0)
    tree = ET.parse(out)
    assert tree.getroot().tag == "osm"


def test_no_lanelet_relation_without_both_boundaries(tmp_path: Path):
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n0",
                polyline=[(0.0, 0.0), (5.0, 0.0)],
                attributes={},
            )
        ],
    )
    out = tmp_path / "n.ll.osm"
    export_lanelet2(g, out, origin_lat=52.0, origin_lon=13.0)
    relations = [el for el in ET.parse(out).getroot() if el.tag == "relation"]
    assert relations == []
