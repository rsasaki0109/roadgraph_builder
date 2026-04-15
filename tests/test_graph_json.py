from __future__ import annotations

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node


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
    g2 = Graph.from_dict(d)
    assert len(g2.nodes) == 2
    assert g2.edges[0].polyline[1] == (1.0, 2.0)


def test_from_dict_allows_omitted_schema_version():
    g = Graph.from_dict(
        {
            "nodes": [{"id": "n0", "position": {"x": 0.0, "y": 0.0}}],
            "edges": [],
        }
    )
    assert len(g.nodes) == 1
