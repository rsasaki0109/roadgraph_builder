from __future__ import annotations

from roadgraph_builder.pipeline.build_graph import BuildParams, polylines_to_graph


def _classify(graph, node_id: str) -> str:
    n = next(n for n in graph.nodes if n.id == node_id)
    return n.attributes.get("junction_type", "")


def _find_multi_branch_node(graph):
    return next(n for n in graph.nodes if n.attributes.get("junction_hint") == "multi_branch")


def test_t_junction_three_edges_through_plus_perpendicular_branch():
    west = [(-50.0, 0.0), (-25.0, 0.0), (0.0, 0.0)]
    east = [(0.0, 0.0), (25.0, 0.0), (50.0, 0.0)]
    south_branch = [(0.0, 0.0), (0.0, -25.0), (0.0, -50.0)]
    g = polylines_to_graph([west, east, south_branch], BuildParams(merge_endpoint_m=5.0))
    node = _find_multi_branch_node(g)
    assert node.attributes["junction_type"] == "t_junction"


def test_y_junction_three_edges_no_collinear_pair():
    import math

    branches = []
    for angle_deg in (0.0, 120.0, 240.0):
        a = math.radians(angle_deg)
        end = (50.0 * math.cos(a), 50.0 * math.sin(a))
        branches.append([(0.0, 0.0), (0.5 * end[0], 0.5 * end[1]), end])
    g = polylines_to_graph(branches, BuildParams(merge_endpoint_m=5.0))
    node = _find_multi_branch_node(g)
    assert node.attributes["junction_type"] == "y_junction"


def test_crossroads_plus_shape():
    n = [(0.0, 0.0), (0.0, 25.0), (0.0, 50.0)]
    s = [(0.0, 0.0), (0.0, -25.0), (0.0, -50.0)]
    e = [(0.0, 0.0), (25.0, 0.0), (50.0, 0.0)]
    w = [(0.0, 0.0), (-25.0, 0.0), (-50.0, 0.0)]
    g = polylines_to_graph([n, s, e, w], BuildParams(merge_endpoint_m=5.0))
    node = _find_multi_branch_node(g)
    assert node.attributes["junction_type"] == "crossroads"


def test_x_junction_skewed_four_way():
    import math

    arms = []
    for angle_deg in (20.0, 200.0, 70.0, 250.0):
        a = math.radians(angle_deg)
        end = (60.0 * math.cos(a), 60.0 * math.sin(a))
        arms.append([(0.0, 0.0), (0.5 * end[0], 0.5 * end[1]), end])
    g = polylines_to_graph(arms, BuildParams(merge_endpoint_m=5.0))
    node = _find_multi_branch_node(g)
    # Two collinear pairs (20/200 and 70/250) at a ~50° crossing angle → x_junction.
    assert node.attributes["junction_type"] == "x_junction"


def test_complex_junction_five_edges():
    import math

    arms = []
    for angle_deg in (0.0, 72.0, 144.0, 216.0, 288.0):
        a = math.radians(angle_deg)
        end = (60.0 * math.cos(a), 60.0 * math.sin(a))
        arms.append([(0.0, 0.0), (0.5 * end[0], 0.5 * end[1]), end])
    g = polylines_to_graph(arms, BuildParams(merge_endpoint_m=5.0))
    node = _find_multi_branch_node(g)
    assert node.attributes["junction_type"] == "complex_junction"


def test_non_multi_branch_nodes_have_no_junction_type():
    through = [(-50.0, 0.0), (-25.0, 0.0), (0.0, 0.0)]
    east = [(0.0, 0.0), (25.0, 0.0), (50.0, 0.0)]
    g = polylines_to_graph([through, east], BuildParams(merge_endpoint_m=5.0))
    for n in g.nodes:
        if n.attributes.get("junction_hint") != "multi_branch":
            assert "junction_type" not in n.attributes
