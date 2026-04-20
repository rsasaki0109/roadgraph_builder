"""3D1: slope inference tests.

Verifies that enrich_sd_to_hd propagates slope_deg into hd block when
elevation data is already on the edge from a 3D build.
"""

from __future__ import annotations

import math

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd


def _make_sloped_graph(slope: float = 0.1) -> Graph:
    """Minimal graph with a single edge that has slope_deg pre-annotated."""
    length = 100.0
    dz = length * slope
    nodes = [
        Node(id="n0", position=(0.0, 0.0), attributes={"elevation_m": 0.0}),
        Node(id="n1", position=(length, 0.0), attributes={"elevation_m": dz}),
    ]
    expected_slope_deg = math.degrees(math.atan2(dz, length))
    edges = [
        Edge(
            id="e0",
            start_node_id="n0",
            end_node_id="n1",
            polyline=[(0.0, 0.0), (length, 0.0)],
            attributes={
                "slope_deg": expected_slope_deg,
                "polyline_z": [0.0, dz],
                "kind": "lane_centerline",
            },
        )
    ]
    return Graph(nodes=nodes, edges=edges)


def test_slope_deg_in_hd_block_after_enrich():
    """After enrich_sd_to_hd, slope_deg appears in edge.attributes.hd."""
    g = _make_sloped_graph(slope=0.1)
    enrich_sd_to_hd(g, SDToHDConfig())
    e = g.edges[0]
    hd = e.attributes.get("hd")
    assert isinstance(hd, dict), "hd block must be a dict"
    sd = hd.get("slope_deg")
    assert sd is not None, "slope_deg must be in hd block"
    expected = math.degrees(math.atan(0.1))
    assert abs(float(sd) - expected) < 0.5, f"slope_deg={sd:.3f}° expected ~{expected:.3f}°"


def test_elevation_m_in_node_hd_block():
    """After enrich_sd_to_hd, elevation_m in node.attributes is mirrored into hd block."""
    g = _make_sloped_graph(slope=0.05)
    enrich_sd_to_hd(g, SDToHDConfig())
    n1 = next(n for n in g.nodes if n.id == "n1")
    hd = n1.attributes.get("hd")
    assert isinstance(hd, dict)
    assert hd.get("elevation_m") is not None
    assert abs(float(hd["elevation_m"]) - 5.0) < 0.01


def test_slope_deg_sign_uphill():
    """Uphill edge (start < end z) should give positive slope_deg."""
    g = _make_sloped_graph(slope=0.1)
    enrich_sd_to_hd(g, SDToHDConfig())
    hd = g.edges[0].attributes["hd"]
    assert float(hd["slope_deg"]) > 0.0


def test_slope_deg_zero_for_flat_edge():
    """Flat edge (no z data) should yield no slope_deg in hd (None → absent)."""
    nodes = [
        Node(id="n0", position=(0.0, 0.0)),
        Node(id="n1", position=(100.0, 0.0)),
    ]
    edges = [
        Edge(
            id="e0",
            start_node_id="n0",
            end_node_id="n1",
            polyline=[(0.0, 0.0), (100.0, 0.0)],
            attributes={"kind": "lane_centerline"},
        )
    ]
    g = Graph(nodes=nodes, edges=edges)
    enrich_sd_to_hd(g, SDToHDConfig())
    hd = g.edges[0].attributes.get("hd", {})
    assert "slope_deg" not in hd, "No slope_deg expected when edge has no elevation data"
