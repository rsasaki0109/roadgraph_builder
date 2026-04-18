from __future__ import annotations

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.pipeline.build_graph import consolidate_clustered_junctions


def _junction_graph_two_close_multi_branch_nodes():
    # Two multi_branch nodes (n_j and n_j2) a couple of meters apart, each
    # connecting three dead-end arms.
    return Graph(
        nodes=[
            Node(id="a", position=(-50.0, 0.0), attributes={"junction_hint": "dead_end", "degree": 1}),
            Node(id="b", position=(50.0, 0.0), attributes={"junction_hint": "dead_end", "degree": 1}),
            Node(id="c", position=(0.0, 50.0), attributes={"junction_hint": "dead_end", "degree": 1}),
            Node(id="d", position=(0.0, -50.0), attributes={"junction_hint": "dead_end", "degree": 1}),
            Node(id="j0", position=(0.0, 0.0), attributes={"junction_hint": "multi_branch", "degree": 3}),
            Node(id="j1", position=(2.0, 0.0), attributes={"junction_hint": "multi_branch", "degree": 3}),
        ],
        edges=[
            Edge(id="e0", start_node_id="a", end_node_id="j0", polyline=[(-50, 0), (0, 0)]),
            Edge(id="e1", start_node_id="j0", end_node_id="c", polyline=[(0, 0), (0, 50)]),
            Edge(id="e2", start_node_id="j0", end_node_id="d", polyline=[(0, 0), (0, -50)]),
            Edge(id="e3", start_node_id="j1", end_node_id="b", polyline=[(2, 0), (50, 0)]),
            Edge(id="e4", start_node_id="j1", end_node_id="c", polyline=[(2, 0), (0, 50)]),
            Edge(id="e5", start_node_id="j1", end_node_id="d", polyline=[(2, 0), (0, -50)]),
        ],
    )


def test_consolidates_two_close_junctions_into_one():
    g = _junction_graph_two_close_multi_branch_nodes()
    absorbed = consolidate_clustered_junctions(g, tolerance_m=5.0)
    assert absorbed == 1
    # j0 < j1 lexicographically → j0 is kept as canonical.
    assert any(n.id == "j0" for n in g.nodes)
    assert not any(n.id == "j1" for n in g.nodes)
    # Centroid of (0, 0) and (2, 0) is (1, 0).
    canon = next(n for n in g.nodes if n.id == "j0")
    assert canon.position == (1.0, 0.0)
    # Every edge that referenced j1 is rewritten to j0.
    for e in g.edges:
        assert "j1" not in (e.start_node_id, e.end_node_id)


def test_no_consolidation_when_nodes_far_apart():
    g = _junction_graph_two_close_multi_branch_nodes()
    absorbed = consolidate_clustered_junctions(g, tolerance_m=1.0)
    assert absorbed == 0
    assert {n.id for n in g.nodes} == {"a", "b", "c", "d", "j0", "j1"}


def test_ignores_non_multi_branch_nodes():
    # Two dead-ends 1 m apart — not a junction cluster, should stay put.
    g = Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0), attributes={"junction_hint": "dead_end", "degree": 1}),
            Node(id="b", position=(1.0, 0.0), attributes={"junction_hint": "dead_end", "degree": 1}),
        ],
        edges=[],
    )
    absorbed = consolidate_clustered_junctions(g, tolerance_m=5.0)
    assert absorbed == 0
    assert len(g.nodes) == 2
