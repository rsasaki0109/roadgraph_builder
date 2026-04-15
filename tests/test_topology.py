from __future__ import annotations

from roadgraph_builder.pipeline.build_graph import BuildParams, annotate_node_degrees, polylines_to_graph


def test_annotate_degrees_line():
    polys = [[(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]]
    g = polylines_to_graph(polys, BuildParams(merge_endpoint_m=0.5))
    by_id = {n.id: n for n in g.nodes}
    assert by_id["n0"].attributes.get("degree") == 1
    assert by_id["n0"].attributes.get("junction_hint") == "dead_end"
    assert by_id["n1"].attributes.get("degree") == 1
    assert by_id["n1"].attributes.get("junction_hint") == "dead_end"


def test_annotate_degrees_fork():
    polys = [
        [(0.0, 0.0), (1.0, 0.0)],
        [(1.0, 0.0), (2.0, 1.0)],
        [(1.0, 0.0), (2.0, -1.0)],
    ]
    g = polylines_to_graph(polys, BuildParams(merge_endpoint_m=0.5))
    center = next(n for n in g.nodes if n.position == (1.0, 0.0))
    assert center.attributes["degree"] == 3
    assert center.attributes["junction_hint"] == "multi_branch"


def test_annotate_idempotent():
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.core.graph.node import Node
    from roadgraph_builder.core.graph.edge import Edge

    g = Graph(
        nodes=[Node(id="a", position=(0, 0)), Node(id="b", position=(1, 0))],
        edges=[Edge("e0", "a", "b", [(0, 0), (1, 0)], {})],
    )
    annotate_node_degrees(g)
    assert g.nodes[0].attributes["degree"] == 1
