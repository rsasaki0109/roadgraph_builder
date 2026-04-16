from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
from roadgraph_builder.io.camera.detections import apply_camera_detections_to_graph, load_camera_detections_json
from roadgraph_builder.io.export.lanelet2 import export_lanelet2


def test_load_and_apply_detections(tmp_path: Path):
    p = tmp_path / "d.json"
    p.write_text(
        json.dumps(
            {
                "format_version": 1,
                "observations": [{"edge_id": "e0", "kind": "speed_limit", "value_kmh": 40}],
            }
        ),
        encoding="utf-8",
    )
    obs = load_camera_detections_json(p)
    assert len(obs) == 1
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n0",
                polyline=[(0.0, 0.0), (1.0, 0.0)],
                attributes={},
            ),
        ],
    )
    apply_camera_detections_to_graph(g, obs)
    rules = g.edges[0].attributes["hd"]["semantic_rules"]
    assert len(rules) == 1
    assert g.metadata["camera_detections"]["edges_touched"] == 1


def test_lanelet_osm_includes_speed_and_regulatory(tmp_path: Path):
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
    apply_camera_detections_to_graph(
        g,
        [
            {"edge_id": "e0", "kind": "speed_limit", "value_kmh": 50},
            {"edge_id": "e0", "kind": "traffic_light", "confidence": 0.85},
        ],
    )
    out = tmp_path / "sem.osm"
    export_lanelet2(g, out, origin_lat=52.5, origin_lon=13.4)
    root = ET.parse(out).getroot()
    relations = [el for el in root if el.tag == "relation"]

    def rel_tags(rel: ET.Element) -> set[tuple[str | None, str | None]]:
        return {(t.get("k"), t.get("v")) for t in rel if t.tag == "tag"}

    lanelets = [r for r in relations if ("type", "lanelet") in rel_tags(r)]
    assert len(lanelets) >= 1
    assert any(("speed_limit", "50") in rel_tags(r) for r in lanelets)
    assert any(("subtype", "traffic_light") in rel_tags(r) for r in relations)
    assert any(("subtype", "road") in rel_tags(r) for r in lanelets)
