"""Tests for export-lanelet2 --per-lane (ROADMAP_0.6.md §α)."""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.export.lanelet2 import export_lanelet2, export_lanelet2_per_lane
from roadgraph_builder.hd.lane_inference import infer_lane_counts

ROOT = Path(__file__).resolve().parent.parent


def _rb() -> str:
    exe = Path(sys.executable).parent / "roadgraph_builder"
    if not exe.is_file():
        pytest.skip(f"roadgraph_builder CLI not found next to {sys.executable}")
    return str(exe)

ORIGIN_LAT = 48.87
ORIGIN_LON = 2.34


def _make_graph_with_lane_data(lane_count: int) -> Graph:
    """Build a simple 2-node graph with hd.lanes[] pre-computed."""
    n0 = Node("n0", (0.0, 0.0))
    n1 = Node("n1", (20.0, 0.0))
    polyline = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]

    # Compute lane geometries via the inference module.
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
    # Build lane_markings with lane_count+1 columns (evenly spaced).
    base_w = 3.5
    half_w = base_w / 2.0
    spacing = base_w  # one lane = one base width
    # columns: -(lane_count/2)*spacing ... +(lane_count/2)*spacing
    col_offsets = [-(lane_count / 2) * spacing + i * spacing for i in range(lane_count + 1)]
    candidates = []
    for off in col_offsets:
        candidates.append({
            "edge_id": "e0",
            "side": "center",
            "polyline_m": [[0.0, off], [20.0, off]],
            "intensity_median": 200.0,
            "point_count": 5,
        })
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
            "lane_inference_sources": inf.sources_used,
        }
    }
    return Graph(nodes=[n0, n1], edges=[edge])


def _count_lanelets(osm_path: Path) -> int:
    tree = ET.parse(osm_path)
    root = tree.getroot()
    count = 0
    for rel in root.findall("relation"):
        tags = {t.get("k"): t.get("v") for t in rel.findall("tag")}
        if tags.get("type") == "lanelet":
            count += 1
    return count


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestPerLaneExport:
    def test_per_lane_2_lanes_gives_2_lanelets(self, tmp_path):
        graph = _make_graph_with_lane_data(lane_count=2)
        out = tmp_path / "map.osm"
        export_lanelet2_per_lane(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        assert _count_lanelets(out) == 2

    def test_per_lane_3_lanes_gives_3_lanelets(self, tmp_path):
        graph = _make_graph_with_lane_data(lane_count=3)
        out = tmp_path / "map.osm"
        export_lanelet2_per_lane(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        assert _count_lanelets(out) == 3

    def test_per_lane_lane_index_tags_present(self, tmp_path):
        graph = _make_graph_with_lane_data(lane_count=2)
        out = tmp_path / "map.osm"
        export_lanelet2_per_lane(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        tree = ET.parse(out)
        root = tree.getroot()
        lane_indices_found = set()
        for rel in root.findall("relation"):
            tags = {t.get("k"): t.get("v") for t in rel.findall("tag")}
            if tags.get("type") == "lanelet" and "roadgraph:lane_index" in tags:
                lane_indices_found.add(int(tags["roadgraph:lane_index"]))
        assert lane_indices_found == {0, 1}

    def test_per_lane_lane_change_relations_emitted(self, tmp_path):
        """Adjacent lanelets on the same edge should have a lane_change relation."""
        graph = _make_graph_with_lane_data(lane_count=2)
        out = tmp_path / "map.osm"
        export_lanelet2_per_lane(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        tree = ET.parse(out)
        root = tree.getroot()
        lane_change_count = 0
        for rel in root.findall("relation"):
            tags = {t.get("k"): t.get("v") for t in rel.findall("tag")}
            if tags.get("subtype") == "lane_change":
                lane_change_count += 1
        # 2 lanes → 1 adjacent pair → 1 lane_change relation
        assert lane_change_count == 1

    def test_standard_export_unchanged(self, tmp_path):
        """Standard export (without --per-lane) must still produce 0 lanelets
        when there are no lane_boundaries (i.e. same as 0.5.0 baseline)."""
        n0 = Node("n0", (0.0, 0.0))
        n1 = Node("n1", (10.0, 0.0))
        e = Edge("e0", "n0", "n1", [(0.0, 0.0), (10.0, 0.0)])
        e.attributes = {}
        graph = Graph(nodes=[n0, n1], edges=[e])
        out = tmp_path / "map.osm"
        export_lanelet2(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        # No lane boundaries → no lanelet relations in standard output.
        assert _count_lanelets(out) == 0

    def test_no_lanes_data_fallback_to_standard(self, tmp_path):
        """Edge without hd.lanes[] should fall back to standard output."""
        n0 = Node("n0", (0.0, 0.0))
        n1 = Node("n1", (10.0, 0.0))
        e = Edge("e0", "n0", "n1", [(0.0, 0.0), (10.0, 0.0)])
        e.attributes = {}
        graph = Graph(nodes=[n0, n1], edges=[e])
        out = tmp_path / "map.osm"
        export_lanelet2_per_lane(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        assert _count_lanelets(out) == 0


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


class TestPerLaneCLI:
    def _write_graph(self, path: Path) -> None:
        """Write a graph that already has hd.lanes[] (2 lanes) for the CLI test."""
        # Build graph with lanes programmatically then serialize.
        graph = _make_graph_with_lane_data(lane_count=2)
        from roadgraph_builder.io.export.json_exporter import export_graph_json
        export_graph_json(graph, path)

    def test_per_lane_cli_flag(self, tmp_path):
        graph_path = tmp_path / "graph.json"
        out_osm = tmp_path / "map.osm"
        self._write_graph(graph_path)

        result = subprocess.run(
            [_rb(), "export-lanelet2", str(graph_path), str(out_osm),
             "--origin-lat", str(ORIGIN_LAT), "--origin-lon", str(ORIGIN_LON), "--per-lane"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert _count_lanelets(out_osm) == 2

    def test_without_per_lane_flag_legacy_behavior(self, tmp_path):
        """Without --per-lane the output must NOT have per-lane lanelets (backward compat)."""
        graph_path = tmp_path / "graph.json"
        out_osm = tmp_path / "map.osm"
        self._write_graph(graph_path)

        result = subprocess.run(
            [_rb(), "export-lanelet2", str(graph_path), str(out_osm),
             "--origin-lat", str(ORIGIN_LAT), "--origin-lon", str(ORIGIN_LON)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        # Standard export of this graph (which has no lane_boundaries) → 0 lanelets.
        assert _count_lanelets(out_osm) == 0
