from __future__ import annotations

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
from roadgraph_builder.io.export.json_loader import load_graph_json
from roadgraph_builder.validation import validate_road_graph_document


def test_enrich_attaches_metadata_and_hd_slots():
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n0",
                polyline=[(0.0, 0.0), (1.0, 0.0)],
                attributes={"k": 1},
            )
        ],
    )
    enrich_sd_to_hd(g)
    assert "sd_to_hd" in g.metadata
    sd = g.metadata["sd_to_hd"]
    assert isinstance(sd, dict)
    assert sd.get("status") == "envelope"
    assert g.edges[0].attributes["k"] == 1
    assert "hd" in g.edges[0].attributes
    assert g.edges[0].attributes["hd"]["lane_boundaries"]["left"] == []
    assert "hd" in g.nodes[0].attributes


def test_enrich_lane_width_fills_boundaries():
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n0",
                polyline=[(0.0, 0.0), (4.0, 0.0)],
                attributes={},
            )
        ],
    )
    enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=2.0))
    hb = g.edges[0].attributes["hd"]["lane_boundaries"]
    assert isinstance(hb, dict)
    assert len(hb["left"]) == 2
    assert g.edges[0].attributes["hd"]["quality"] == "centerline_offset_hd_lite"
    sd = g.metadata["sd_to_hd"]
    assert isinstance(sd, dict)
    assert sd.get("status") == "centerline_boundaries_hd_lite"


def test_enriched_graph_validates():
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n0",
                polyline=[(0.0, 0.0)],
                attributes={},
            )
        ],
    )
    enrich_sd_to_hd(g)
    validate_road_graph_document(g.to_dict())


def test_graph_roundtrip_with_metadata(tmp_path):
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n0",
                polyline=[(0.0, 0.0)],
                attributes={},
            )
        ],
        metadata={"foo": "bar"},
    )
    p = tmp_path / "g.json"
    p.write_text(__import__("json").dumps(g.to_dict()), encoding="utf-8")
    g2 = load_graph_json(p)
    assert g2.metadata.get("foo") == "bar"
