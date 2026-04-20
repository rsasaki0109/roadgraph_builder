"""Tests for A1: camera_detections wiring into Lanelet2 regulatory_element export.

Covers:
- traffic_light detection produces subtype=traffic_light regulatory_element
- stop_line detection produces type=line_thin, subtype=solid way
- existing export_lanelet2 output is byte-identical when camera_detections=None
- validate-lanelet2-tags passes on output with camera_detections
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.export.lanelet2 import export_lanelet2, validate_lanelet2_tags

ORIGIN_LAT = 48.87
ORIGIN_LON = 2.34


def _make_graph_with_hd() -> Graph:
    """Single-edge graph with lane_boundaries so lanelet relations are emitted."""
    n0 = Node("n0", (0.0, 0.0))
    n1 = Node("n1", (20.0, 0.0))
    e = Edge("e0", "n0", "n1", [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)])
    e.attributes = {
        "hd": {
            "lane_boundaries": {
                "left": [
                    {"x": 0.0, "y": 1.75},
                    {"x": 10.0, "y": 1.75},
                    {"x": 20.0, "y": 1.75},
                ],
                "right": [
                    {"x": 0.0, "y": -1.75},
                    {"x": 10.0, "y": -1.75},
                    {"x": 20.0, "y": -1.75},
                ],
            },
            "semantic_rules": [],
        }
    }
    return Graph(nodes=[n0, n1], edges=[e])


def _parse_all_relations(path: Path) -> list[dict]:
    tree = ET.parse(path)
    root = tree.getroot()
    result = []
    for rel in root.findall("relation"):
        tags = {t.get("k"): t.get("v") for t in rel.findall("tag")}
        members = [
            {"type": m.get("type"), "ref": m.get("ref"), "role": m.get("role")}
            for m in rel.findall("member")
        ]
        result.append({"tags": tags, "members": members})
    return result


def _parse_all_ways(path: Path) -> list[dict]:
    tree = ET.parse(path)
    root = tree.getroot()
    result = []
    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        result.append({"id": way.get("id"), "tags": tags})
    return result


# ---------------------------------------------------------------------------
# A1 acceptance test: traffic_light → regulatory_element relation
# ---------------------------------------------------------------------------


class TestTrafficLightWiring:
    def test_traffic_light_produces_regulatory_element(self, tmp_path):
        """A traffic_light detection → subtype=traffic_light regulatory_element."""
        graph = _make_graph_with_hd()
        cam_det = {
            "format_version": 1,
            "observations": [
                {
                    "edge_id": "e0",
                    "kind": "traffic_light",
                    "world_xy_m": {"x": 5.0, "y": 2.0},
                    "confidence": 0.9,
                }
            ],
        }
        out = tmp_path / "map.osm"
        export_lanelet2(
            graph,
            out,
            origin_lat=ORIGIN_LAT,
            origin_lon=ORIGIN_LON,
            camera_detections=cam_det,
        )
        rels = _parse_all_relations(out)
        tl_rels = [
            r
            for r in rels
            if r["tags"].get("type") == "regulatory_element"
            and r["tags"].get("subtype") == "traffic_light"
        ]
        assert len(tl_rels) == 1, f"expected 1 traffic_light regulatory_element, got {len(tl_rels)}"

    def test_traffic_light_refers_member_present(self, tmp_path):
        """The traffic_light relation has a 'refers' member pointing to the lanelet."""
        graph = _make_graph_with_hd()
        cam_det = {
            "format_version": 1,
            "observations": [
                {
                    "edge_id": "e0",
                    "kind": "traffic_light",
                    "world_xy_m": [5.0, 2.0],
                }
            ],
        }
        out = tmp_path / "map.osm"
        export_lanelet2(
            graph,
            out,
            origin_lat=ORIGIN_LAT,
            origin_lon=ORIGIN_LON,
            camera_detections=cam_det,
        )
        rels = _parse_all_relations(out)
        tl_rels = [
            r
            for r in rels
            if r["tags"].get("subtype") == "traffic_light"
        ]
        assert len(tl_rels) == 1
        refers_members = [m for m in tl_rels[0]["members"] if m["role"] == "refers"]
        assert len(refers_members) >= 1

    def test_traffic_light_without_world_xy_is_skipped(self, tmp_path):
        """If world_xy_m is absent, no regulatory_element is emitted."""
        graph = _make_graph_with_hd()
        cam_det = {
            "observations": [
                {"edge_id": "e0", "kind": "traffic_light"},  # no world_xy_m
            ]
        }
        out = tmp_path / "map.osm"
        export_lanelet2(
            graph,
            out,
            origin_lat=ORIGIN_LAT,
            origin_lon=ORIGIN_LON,
            camera_detections=cam_det,
        )
        rels = _parse_all_relations(out)
        tl_rels = [
            r for r in rels if r["tags"].get("subtype") == "traffic_light"
        ]
        assert len(tl_rels) == 0


# ---------------------------------------------------------------------------
# A1 acceptance test: stop_line → way with type=line_thin, subtype=solid
# ---------------------------------------------------------------------------


class TestStopLineWiring:
    def test_stop_line_produces_way(self, tmp_path):
        """A stop_line detection with a polyline → type=line_thin, subtype=solid way."""
        graph = _make_graph_with_hd()
        cam_det = {
            "format_version": 1,
            "observations": [
                {
                    "edge_id": "e0",
                    "kind": "stop_line",
                    "polyline_m": [[9.0, -1.75], [9.0, 1.75]],
                }
            ],
        }
        out = tmp_path / "map.osm"
        export_lanelet2(
            graph,
            out,
            origin_lat=ORIGIN_LAT,
            origin_lon=ORIGIN_LON,
            camera_detections=cam_det,
        )
        ways = _parse_all_ways(out)
        stop_line_ways = [
            w for w in ways if w["tags"].get("subtype") == "solid"
            and w["tags"].get("roadgraph:kind") == "stop_line"
        ]
        assert len(stop_line_ways) == 1

    def test_stop_line_without_polyline_skipped(self, tmp_path):
        """A stop_line with only a single world_xy_m (not a polyline) is skipped."""
        graph = _make_graph_with_hd()
        cam_det = {
            "observations": [
                {
                    "kind": "stop_line",
                    "world_xy_m": {"x": 9.0, "y": 0.0},  # single point, not a line
                }
            ]
        }
        out = tmp_path / "map.osm"
        export_lanelet2(
            graph,
            out,
            origin_lat=ORIGIN_LAT,
            origin_lon=ORIGIN_LON,
            camera_detections=cam_det,
        )
        ways = _parse_all_ways(out)
        stop_line_ways = [
            w for w in ways if w["tags"].get("roadgraph:kind") == "stop_line"
        ]
        assert len(stop_line_ways) == 0


# ---------------------------------------------------------------------------
# A1 acceptance test: both together (1 traffic_light + 1 stop_line)
# ---------------------------------------------------------------------------


class TestCombinedDetections:
    def test_one_traffic_light_one_stop_line(self, tmp_path):
        """Combined: 1 traffic_light relation + 1 stop_line way."""
        graph = _make_graph_with_hd()
        cam_det = {
            "format_version": 1,
            "observations": [
                {
                    "edge_id": "e0",
                    "kind": "traffic_light",
                    "world_xy_m": {"x": 8.0, "y": 2.0},
                    "confidence": 0.85,
                },
                {
                    "edge_id": "e0",
                    "kind": "stop_line",
                    "polyline_m": [[9.0, -1.75], [9.0, 1.75]],
                },
            ],
        }
        out = tmp_path / "map.osm"
        export_lanelet2(
            graph,
            out,
            origin_lat=ORIGIN_LAT,
            origin_lon=ORIGIN_LON,
            camera_detections=cam_det,
        )
        rels = _parse_all_relations(out)
        tl_rels = [
            r for r in rels if r["tags"].get("subtype") == "traffic_light"
        ]
        assert len(tl_rels) == 1, "expected exactly 1 traffic_light regulatory_element"

        ways = _parse_all_ways(out)
        sl_ways = [
            w for w in ways if w["tags"].get("roadgraph:kind") == "stop_line"
        ]
        assert len(sl_ways) == 1, "expected exactly 1 stop_line way"


# ---------------------------------------------------------------------------
# A1 backward compat: no camera_detections → byte-identical
# ---------------------------------------------------------------------------


class TestBackwardCompatNoCameraDetections:
    def test_no_camera_detections_byte_identical(self, tmp_path):
        """export_lanelet2 with camera_detections=None is byte-identical to omitting the arg."""
        graph = _make_graph_with_hd()
        out1 = tmp_path / "map1.osm"
        out2 = tmp_path / "map2.osm"
        export_lanelet2(graph, out1, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        export_lanelet2(
            graph,
            out2,
            origin_lat=ORIGIN_LAT,
            origin_lon=ORIGIN_LON,
            camera_detections=None,
        )
        assert out1.read_bytes() == out2.read_bytes()


# ---------------------------------------------------------------------------
# A1: validate-lanelet2-tags still passes on output with camera_detections
# ---------------------------------------------------------------------------


class TestValidationWithCameraDetections:
    def test_validate_tags_passes_with_traffic_light(self, tmp_path):
        """validate_lanelet2_tags returns no errors on a map with traffic_light wiring."""
        graph = _make_graph_with_hd()
        cam_det = {
            "observations": [
                {
                    "edge_id": "e0",
                    "kind": "traffic_light",
                    "world_xy_m": {"x": 5.0, "y": 2.0},
                }
            ]
        }
        out = tmp_path / "map.osm"
        export_lanelet2(
            graph,
            out,
            origin_lat=ORIGIN_LAT,
            origin_lon=ORIGIN_LON,
            camera_detections=cam_det,
        )
        errors, _ = validate_lanelet2_tags(out)
        assert errors == [], f"unexpected errors: {errors}"
