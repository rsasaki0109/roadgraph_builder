"""3D1: Lanelet2 export elevation tests.

Verifies:
  - Nodes with elevation_m emit <tag k="ele" .../> in Lanelet2 OSM output.
  - Nodes without elevation_m emit no ele tag (backward compat).
  - 2D export (no elevation) is unchanged from v0.6.0 behaviour.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
from roadgraph_builder.io.export.lanelet2 import export_lanelet2


def _make_3d_graph() -> Graph:
    nodes = [
        Node(id="n0", position=(0.0, 0.0), attributes={"elevation_m": 10.0}),
        Node(id="n1", position=(50.0, 0.0), attributes={"elevation_m": 15.0}),
    ]
    edges = [
        Edge(
            id="e0",
            start_node_id="n0",
            end_node_id="n1",
            polyline=[(0.0, 0.0), (50.0, 0.0)],
            attributes={"slope_deg": 5.7, "polyline_z": [10.0, 15.0]},
        )
    ]
    g = Graph(nodes=nodes, edges=edges)
    enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=3.5))
    return g


def _make_2d_graph() -> Graph:
    """2D graph with no elevation data."""
    nodes = [
        Node(id="n0", position=(0.0, 0.0)),
        Node(id="n1", position=(50.0, 0.0)),
    ]
    edges = [
        Edge(
            id="e0",
            start_node_id="n0",
            end_node_id="n1",
            polyline=[(0.0, 0.0), (50.0, 0.0)],
            attributes={},
        )
    ]
    g = Graph(nodes=nodes, edges=edges)
    enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=3.5))
    return g


def test_3d_export_has_ele_tags(tmp_path: Path):
    """Nodes with elevation_m get <tag k='ele' .../> in the OSM output."""
    g = _make_3d_graph()
    out = tmp_path / "map_3d.osm"
    export_lanelet2(g, out, origin_lat=35.0, origin_lon=135.0)

    tree = ET.parse(out)
    root = tree.getroot()
    osm_nodes = [el for el in root if el.tag == "node"]
    ele_values = [
        t.get("v")
        for n in osm_nodes
        for t in n
        if t.tag == "tag" and t.get("k") == "ele"
    ]
    assert len(ele_values) >= 2, f"Expected ≥ 2 ele tags, found {len(ele_values)}: {ele_values}"
    # Check that the values are numeric
    for val in ele_values:
        assert val is not None
        float(val)  # must parse as float


def test_3d_export_ele_value_matches(tmp_path: Path):
    """The ele tag value must match the node's elevation_m."""
    g = _make_3d_graph()
    out = tmp_path / "map_3d.osm"
    export_lanelet2(g, out, origin_lat=35.0, origin_lon=135.0)

    tree = ET.parse(out)
    root = tree.getroot()
    osm_nodes = [el for el in root if el.tag == "node"]
    ele_vals = []
    for n_el in osm_nodes:
        tags = {t.get("k"): t.get("v") for t in n_el if t.tag == "tag"}
        if "ele" in tags and tags.get("roadgraph") == "graph_node":
            ele_vals.append(float(tags["ele"]))
    assert sorted(ele_vals) == sorted([10.0, 15.0]), (
        f"ele values {sorted(ele_vals)} != [10.0, 15.0]"
    )


def test_2d_export_has_no_ele_tags(tmp_path: Path):
    """2D graph (no elevation) must produce no ele tags — backward compat."""
    g = _make_2d_graph()
    out = tmp_path / "map_2d.osm"
    export_lanelet2(g, out, origin_lat=35.0, origin_lon=135.0)

    tree = ET.parse(out)
    root = tree.getroot()
    ele_tags = [
        t
        for el in root
        for t in el
        if t.tag == "tag" and t.get("k") == "ele"
    ]
    assert len(ele_tags) == 0, (
        f"2D export should have no ele tags, found {len(ele_tags)}"
    )
