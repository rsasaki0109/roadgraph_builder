"""Tests for A3: Lanelet2 lane_change relation in per-lane export.

Covers:
- 2-lane edge → 1 lane_change relation (adjacent pair)
- 3-lane edge → 2 lane_change relations
- lane_change relation has subtype=lane_change
- sign tag is present on lane_change relations
- lane_markings with solid markers produces sign=solid
- lane_markings absent defaults to sign=dashed
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.hd.lane_inference import infer_lane_counts
from roadgraph_builder.io.export.lanelet2 import export_lanelet2_per_lane

ORIGIN_LAT = 48.87
ORIGIN_LON = 2.34


def _make_graph_with_lane_data(lane_count: int) -> Graph:
    """Build a 2-node, 1-edge graph with hd.lanes[] pre-populated."""
    n0 = Node("n0", (0.0, 0.0))
    n1 = Node("n1", (20.0, 0.0))
    polyline = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]

    graph_json = {
        "schema_version": 1,
        "nodes": [
            {"id": "n0", "position": {"x": 0.0, "y": 0.0}, "attributes": {}},
            {"id": "n1", "position": {"x": 20.0, "y": 0.0}, "attributes": {}},
        ],
        "edges": [
            {
                "id": "e0",
                "start_node_id": "n0",
                "end_node_id": "n1",
                "polyline": [{"x": p[0], "y": p[1]} for p in polyline],
                "attributes": {},
            }
        ],
    }
    base_w = 3.5
    col_offsets = [-(lane_count / 2) * base_w + i * base_w for i in range(lane_count + 1)]
    candidates = [
        {
            "edge_id": "e0",
            "side": "center",
            "polyline_m": [[0.0, off], [20.0, off]],
            "intensity_median": 200.0,
            "point_count": 5,
        }
        for off in col_offsets
    ]
    lm = {"candidates": candidates}
    inferences = infer_lane_counts(graph_json, lane_markings=lm, base_lane_width_m=base_w)
    inf = inferences[0]

    edge = Edge("e0", "n0", "n1", polyline)
    edge.attributes = {
        "hd": {
            "lane_count": inf.lane_count,
            "lanes": [
                {
                    "lane_index": lg.lane_index,
                    "offset_m": lg.offset_m,
                    "centerline_m": [list(pt) for pt in lg.centerline_m],
                    "confidence": lg.confidence,
                }
                for lg in inf.lanes
            ],
        }
    }
    return Graph(nodes=[n0, n1], edges=[edge])


def _parse_lane_change_relations(path: Path) -> list[dict]:
    tree = ET.parse(path)
    root = tree.getroot()
    result = []
    for rel in root.findall("relation"):
        tags = {t.get("k"): t.get("v") for t in rel.findall("tag")}
        if tags.get("subtype") == "lane_change":
            result.append({"tags": tags})
    return result


class TestLaneChangeRelationCount:
    def test_two_lanes_one_lane_change_relation(self, tmp_path):
        """2 adjacent lanelets → 1 lane_change relation."""
        graph = _make_graph_with_lane_data(2)
        out = tmp_path / "map.osm"
        export_lanelet2_per_lane(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        rels = _parse_lane_change_relations(out)
        assert len(rels) == 1

    def test_three_lanes_two_lane_change_relations(self, tmp_path):
        """3 lanelets → 2 adjacent pairs → 2 lane_change relations."""
        graph = _make_graph_with_lane_data(3)
        out = tmp_path / "map.osm"
        export_lanelet2_per_lane(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        rels = _parse_lane_change_relations(out)
        assert len(rels) == 2


class TestLaneChangeRelationTags:
    def test_lane_change_relation_has_subtype(self, tmp_path):
        """Every lane_change relation has subtype=lane_change."""
        graph = _make_graph_with_lane_data(2)
        out = tmp_path / "map.osm"
        export_lanelet2_per_lane(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        rels = _parse_lane_change_relations(out)
        assert len(rels) == 1
        assert rels[0]["tags"].get("subtype") == "lane_change"

    def test_lane_change_relation_has_sign_tag(self, tmp_path):
        """Every lane_change relation must carry a 'sign' tag (A3)."""
        graph = _make_graph_with_lane_data(2)
        out = tmp_path / "map.osm"
        export_lanelet2_per_lane(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        rels = _parse_lane_change_relations(out)
        assert len(rels) == 1
        assert "sign" in rels[0]["tags"], "lane_change relation missing 'sign' tag"

    def test_no_lane_markings_defaults_to_dashed(self, tmp_path):
        """Without lane_markings arg, sign defaults to 'dashed'."""
        graph = _make_graph_with_lane_data(2)
        out = tmp_path / "map.osm"
        export_lanelet2_per_lane(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        rels = _parse_lane_change_relations(out)
        assert rels[0]["tags"].get("sign") == "dashed"

    def test_solid_lane_markings_produces_solid_sign(self, tmp_path):
        """High-intensity solid lane markings → sign=solid on lane_change relation."""
        graph = _make_graph_with_lane_data(2)
        # Provide lane_markings with solid-class intensity for edge e0.
        solid_lm = {
            "candidates": [
                {
                    "edge_id": "e0",
                    "side": "left",
                    "intensity_median": 250.0,
                    "point_count": 30,
                    "polyline_m": [[0.0, 1.75], [20.0, 1.75]],
                }
            ]
        }
        out = tmp_path / "map.osm"
        export_lanelet2_per_lane(
            graph, out,
            origin_lat=ORIGIN_LAT,
            origin_lon=ORIGIN_LON,
            lane_markings=solid_lm,
        )
        rels = _parse_lane_change_relations(out)
        assert len(rels) == 1
        assert rels[0]["tags"].get("sign") == "solid"

    def test_dashed_lane_markings_produces_dashed_sign(self, tmp_path):
        """Low-intensity dashed markers → sign=dashed."""
        graph = _make_graph_with_lane_data(2)
        dashed_lm = {
            "candidates": [
                {
                    "edge_id": "e0",
                    "side": "left",
                    "intensity_median": 80.0,
                    "point_count": 3,
                    "polyline_m": [[0.0, 1.75], [20.0, 1.75]],
                }
            ]
        }
        out = tmp_path / "map.osm"
        export_lanelet2_per_lane(
            graph, out,
            origin_lat=ORIGIN_LAT,
            origin_lon=ORIGIN_LON,
            lane_markings=dashed_lm,
        )
        rels = _parse_lane_change_relations(out)
        assert len(rels) == 1
        assert rels[0]["tags"].get("sign") == "dashed"
