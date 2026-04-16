from __future__ import annotations

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.export.bundle import build_sd_nav_document
from roadgraph_builder.navigation.sd_maneuvers import allowed_maneuvers_for_edge, allowed_maneuvers_for_edge_reverse
from roadgraph_builder.pipeline.build_graph import annotate_node_degrees
from roadgraph_builder.validation import validate_sd_nav_document


def _graph_with_degree(g: Graph) -> Graph:
    annotate_node_degrees(g)
    return g


def test_dead_end_includes_u_turn():
    """Single edge: end node degree 1 → can only reverse."""
    n0 = Node(id="n0", position=(0.0, 0.0))
    n1 = Node(id="n1", position=(10.0, 0.0))
    e0 = Edge(
        id="e0",
        start_node_id="n0",
        end_node_id="n1",
        polyline=[(0.0, 0.0), (10.0, 0.0)],
        attributes={},
    )
    g = _graph_with_degree(Graph(nodes=[n0, n1], edges=[e0]))
    m = allowed_maneuvers_for_edge(g, e0)
    assert "straight" in m
    assert "u_turn" in m
    assert "left" not in m and "right" not in m
    mr = allowed_maneuvers_for_edge_reverse(g, e0)
    assert "straight" in mr and "u_turn" in mr


def test_y_junction_east_reverse_has_turns_at_center():
    """Traversing east arm backward: arrive at center with left/right from other arms."""
    nc = Node(id="nc", position=(0.0, 0.0))
    ns = Node(id="ns", position=(0.0, -10.0))
    ne = Node(id="ne", position=(10.0, 0.0))
    nw = Node(id="nw", position=(-10.0, 0.0))
    e_south = Edge(
        id="e_south",
        start_node_id="ns",
        end_node_id="nc",
        polyline=[(0.0, -10.0), (0.0, 0.0)],
        attributes={},
    )
    e_east = Edge(
        id="e_east",
        start_node_id="nc",
        end_node_id="ne",
        polyline=[(0.0, 0.0), (10.0, 0.0)],
        attributes={},
    )
    e_west = Edge(
        id="e_west",
        start_node_id="nc",
        end_node_id="nw",
        polyline=[(0.0, 0.0), (-10.0, 0.0)],
        attributes={},
    )
    g = _graph_with_degree(Graph(nodes=[nc, ns, ne, nw], edges=[e_south, e_east, e_west]))
    mr = allowed_maneuvers_for_edge_reverse(g, e_east)
    assert "left" in mr and "right" in mr
    assert "u_turn" not in mr


def test_y_junction_left_right():
    """Three edges at origin: south approach gets left/right branches."""
    nc = Node(id="nc", position=(0.0, 0.0))
    ns = Node(id="ns", position=(0.0, -10.0))
    ne = Node(id="ne", position=(10.0, 0.0))
    nw = Node(id="nw", position=(-10.0, 0.0))
    e_south = Edge(
        id="e_south",
        start_node_id="ns",
        end_node_id="nc",
        polyline=[(0.0, -10.0), (0.0, -1.0), (0.0, 0.0)],
        attributes={},
    )
    e_east = Edge(
        id="e_east",
        start_node_id="nc",
        end_node_id="ne",
        polyline=[(0.0, 0.0), (10.0, 0.0)],
        attributes={},
    )
    e_west = Edge(
        id="e_west",
        start_node_id="nc",
        end_node_id="nw",
        polyline=[(0.0, 0.0), (-10.0, 0.0)],
        attributes={},
    )
    g = _graph_with_degree(Graph(nodes=[nc, ns, ne, nw], edges=[e_south, e_east, e_west]))
    m = allowed_maneuvers_for_edge(g, e_south)
    assert m[0] == "straight"
    assert "left" in m
    assert "right" in m
    assert "u_turn" not in m


def test_build_sd_nav_document_validates():
    nc = Node(id="nc", position=(0.0, 0.0))
    ns = Node(id="ns", position=(0.0, -10.0))
    ne = Node(id="ne", position=(10.0, 0.0))
    nw = Node(id="nw", position=(-10.0, 0.0))
    e_south = Edge(
        id="e_south",
        start_node_id="ns",
        end_node_id="nc",
        polyline=[(0.0, -10.0), (0.0, 0.0)],
        attributes={},
    )
    e_east = Edge(
        id="e_east",
        start_node_id="nc",
        end_node_id="ne",
        polyline=[(0.0, 0.0), (10.0, 0.0)],
        attributes={},
    )
    e_west = Edge(
        id="e_west",
        start_node_id="nc",
        end_node_id="nw",
        polyline=[(0.0, 0.0), (-10.0, 0.0)],
        attributes={},
    )
    g = _graph_with_degree(Graph(nodes=[nc, ns, ne, nw], edges=[e_south, e_east, e_west]))
    doc = build_sd_nav_document(g)
    validate_sd_nav_document(doc)
    south = next(e for e in doc["edges"] if e["id"] == "e_south")
    assert "left" in south["allowed_maneuvers"] and "right" in south["allowed_maneuvers"]
    assert "straight" in south["allowed_maneuvers_reverse"] and "u_turn" in south["allowed_maneuvers_reverse"]
