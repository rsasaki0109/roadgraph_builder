from __future__ import annotations

import json

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.export.json_exporter import export_graph_json, json_document_payload


def test_graph_roundtrip():
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0)), Node(id="n1", position=(1.0, 2.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, 0.0), (1.0, 2.0)],
                attributes={"k": 1},
            )
        ],
    )
    d = g.to_dict()
    assert d["schema_version"] == 1
    assert "metadata" not in d
    g2 = Graph.from_dict(d)
    assert len(g2.nodes) == 2
    assert g2.edges[0].polyline[1] == (1.0, 2.0)
    assert g2.metadata == {}


def test_from_dict_allows_omitted_schema_version():
    g = Graph.from_dict(
        {
            "nodes": [{"id": "n0", "position": {"x": 0.0, "y": 0.0}}],
            "edges": [],
        }
    )
    assert len(g.nodes) == 1


def test_graph_roundtrip_metadata():
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0))],
        edges=[],
        metadata={"tier": "test"},
    )
    g2 = Graph.from_dict(g.to_dict())
    assert g2.metadata == {"tier": "test"}


def test_json_document_payload_can_write_compact_document():
    pretty = json_document_payload({"items": [1, 2], "name": "road"}, compact=False)
    compact = json_document_payload({"items": [1, 2], "name": "road"}, compact=True)

    assert json.loads(pretty) == json.loads(compact)
    assert pretty.endswith("\n")
    assert compact == '{"items":[1,2],"name":"road"}\n'
    assert len(compact) < len(pretty)


def test_export_graph_json_can_write_compact_document(tmp_path):
    graph = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0)), Node(id="n1", position=(1.0, 2.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, 0.0), (1.0, 2.0)],
                attributes={"k": 1},
            )
        ],
    )
    pretty = tmp_path / "pretty.json"
    compact = tmp_path / "compact.json"

    export_graph_json(graph, pretty)
    export_graph_json(graph, compact, compact=True)

    assert json.loads(compact.read_text(encoding="utf-8")) == json.loads(pretty.read_text(encoding="utf-8"))
    assert compact.stat().st_size < pretty.stat().st_size
