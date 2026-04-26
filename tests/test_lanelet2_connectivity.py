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


def test_lanelet2_emits_directed_lane_connection_pairs_at_junction(tmp_path: Path):
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
    rid_by_edge = {}
    for r in lanelet_relations:
        tags = {t.get("k"): t.get("v") for t in r.findall("tag")}
        rid_by_edge[tags["roadgraph:edge_id"]] = int(r.get("id"))
    rid_w, rid_e, rid_s = rid_by_edge["eW"], rid_by_edge["eE"], rid_by_edge["eS"]

    connections = [
        r
        for r in root.findall("relation")
        if any(
            t.get("k") == "roadgraph" and t.get("v") == "lane_connection"
            for t in r.findall("tag")
        )
    ]
    # Bidirectional T-junction: each of the 3 incident edges contributes both
    # forward and reverse flow at node "j", so every (pred, succ) pair with
    # pred != succ exists. With 3 edges that's 3 * 3 - 3 = 6 directed pairs.
    assert len(connections) == 6

    # Tag set is identical across all directed relations at this junction.
    junction_tags = {t.get("k"): t.get("v") for t in connections[0].findall("tag")}
    assert junction_tags["type"] == "regulatory_element"
    assert junction_tags["subtype"] == "lane_connection"
    assert junction_tags["roadgraph:junction_node_id"] == "j"
    assert junction_tags["roadgraph:junction_type"] == "t_junction"
    assert junction_tags["roadgraph:junction_hint"] == "multi_branch"

    # Each connection has exactly two members: one predecessor, one successor.
    pairs = set()
    for conn in connections:
        members = conn.findall("member")
        assert len(members) == 2
        roles = {m.get("role"): int(m.get("ref")) for m in members}
        assert set(roles.keys()) == {"predecessor", "successor"}
        pairs.add((roles["predecessor"], roles["successor"]))
        assert all(m.get("type") == "relation" for m in members)
    assert pairs == {
        (rid_w, rid_e), (rid_e, rid_w),
        (rid_w, rid_s), (rid_s, rid_w),
        (rid_e, rid_s), (rid_s, rid_e),
    }


def test_lanelet2_oneway_edge_emits_only_one_directed_pair(tmp_path: Path):
    # Two one-way edges sharing a junction: A→j, j→B. Only the forward chain
    # A → B should be emitted as a directed (predecessor, successor) pair.
    g = Graph(
        nodes=[
            Node(id="a", position=(-50.0, 0.0), attributes={"junction_hint": "dead_end"}),
            Node(id="j", position=(0.0, 0.0), attributes={"junction_hint": "multi_branch", "junction_type": "branch", "degree": 2}),
            Node(id="b", position=(50.0, 0.0), attributes={"junction_hint": "dead_end"}),
        ],
        edges=[
            Edge(id="eAj", start_node_id="a", end_node_id="j", polyline=[(-50.0, 0.0), (0.0, 0.0)], attributes={"osm_oneway": "yes"}),
            Edge(id="ejB", start_node_id="j", end_node_id="b", polyline=[(0.0, 0.0), (50.0, 0.0)], attributes={"osm_oneway": "yes"}),
        ],
    )
    enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=3.0))
    out = tmp_path / "oneway.osm"
    export_lanelet2(g, out, origin_lat=52.52, origin_lon=13.405)
    tree = ET.parse(out)
    root = tree.getroot()

    rid_by_edge = {}
    for r in root.findall("relation"):
        tags = {t.get("k"): t.get("v") for t in r.findall("tag")}
        if tags.get("type") == "lanelet":
            rid_by_edge[tags["roadgraph:edge_id"]] = int(r.get("id"))

    connections = [
        r
        for r in root.findall("relation")
        if any(
            t.get("k") == "roadgraph" and t.get("v") == "lane_connection"
            for t in r.findall("tag")
        )
    ]
    assert len(connections) == 1
    members = connections[0].findall("member")
    by_role = {m.get("role"): int(m.get("ref")) for m in members}
    assert by_role == {"predecessor": rid_by_edge["eAj"], "successor": rid_by_edge["ejB"]}


def test_lanelet2_reverse_oneway_flips_predecessor_successor(tmp_path: Path):
    # eA: oneway=yes, polyline a→j, so flow exits at j.
    # eB: oneway=-1, polyline b→j, so flow runs j→b — meaning it ENTERS at j.
    # If we ignored the `-1`, eB would also exit at j and we'd get zero pairs.
    # Correctly handling reverse oneway makes the chain eA → eB at junction j.
    g = Graph(
        nodes=[
            Node(id="a", position=(-50.0, 0.0), attributes={"junction_hint": "dead_end"}),
            Node(id="j", position=(0.0, 0.0), attributes={"junction_hint": "multi_branch", "junction_type": "branch", "degree": 2}),
            Node(id="b", position=(50.0, 0.0), attributes={"junction_hint": "dead_end"}),
        ],
        edges=[
            Edge(id="eA", start_node_id="a", end_node_id="j", polyline=[(-50.0, 0.0), (0.0, 0.0)], attributes={"osm_oneway": "yes"}),
            Edge(id="eB", start_node_id="b", end_node_id="j", polyline=[(50.0, 0.0), (0.0, 0.0)], attributes={"osm_oneway": "-1"}),
        ],
    )
    enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=3.0))
    out = tmp_path / "reverse.osm"
    export_lanelet2(g, out, origin_lat=52.52, origin_lon=13.405)
    tree = ET.parse(out)
    root = tree.getroot()

    rid_by_edge = {}
    for r in root.findall("relation"):
        tags = {t.get("k"): t.get("v") for t in r.findall("tag")}
        if tags.get("type") == "lanelet":
            rid_by_edge[tags["roadgraph:edge_id"]] = int(r.get("id"))

    connections = [
        r
        for r in root.findall("relation")
        if any(
            t.get("k") == "roadgraph" and t.get("v") == "lane_connection"
            for t in r.findall("tag")
        )
    ]
    assert len(connections) == 1
    members = connections[0].findall("member")
    by_role = {m.get("role"): int(m.get("ref")) for m in members}
    assert by_role == {"predecessor": rid_by_edge["eA"], "successor": rid_by_edge["eB"]}


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
