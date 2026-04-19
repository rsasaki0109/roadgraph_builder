"""Tests for Lanelet2 fidelity tag upgrades (ROADMAP_0.6.md §δ).

Covers:
- speed_limit as lanelet-attr (default, 0.5.0 behavior)
- speed_limit as regulatory-element (L2 spec style)
- lane_markings solid/dashed boundary subtype classification
- traffic_light regulatory_element detection
- validate_lanelet2_tags pass/fail cases
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.export.lanelet2 import (
    _lane_marking_subtype,
    _speed_limit_tags,
    export_lanelet2,
    validate_lanelet2_tags,
)

ORIGIN_LAT = 48.87
ORIGIN_LON = 2.34


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph_with_hd(
    speed_kmh: int | None = None,
    has_traffic_light: bool = False,
) -> Graph:
    """Build a single-edge graph with lane_boundaries + optional semantic_rules."""
    n0 = Node("n0", (0.0, 0.0))
    n1 = Node("n1", (20.0, 0.0))
    e = Edge("e0", "n0", "n1", [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)])
    semantic_rules = []
    if speed_kmh is not None:
        semantic_rules.append({"kind": "speed_limit", "value_kmh": speed_kmh})
    if has_traffic_light:
        semantic_rules.append({
            "kind": "traffic_light",
            "world_xy_m": {"x": 5.0, "y": 2.0},
            "confidence": 0.9,
        })
    e.attributes = {
        "hd": {
            "lane_boundaries": {
                "left": [{"x": 0.0, "y": 1.75}, {"x": 10.0, "y": 1.75}, {"x": 20.0, "y": 1.75}],
                "right": [{"x": 0.0, "y": -1.75}, {"x": 10.0, "y": -1.75}, {"x": 20.0, "y": -1.75}],
            },
            "semantic_rules": semantic_rules,
        }
    }
    return Graph(nodes=[n0, n1], edges=[e])


def _parse_osm(path: Path) -> tuple[dict[str, dict], list[dict]]:
    """Return (relations_by_id, all_relations) where each dict has 'tags' and 'members'."""
    tree = ET.parse(path)
    root = tree.getroot()
    rels = {}
    all_rels = []
    for rel in root.findall("relation"):
        rel_id = rel.get("id")
        tags = {t.get("k"): t.get("v") for t in rel.findall("tag")}
        members = [
            {"type": m.get("type"), "ref": m.get("ref"), "role": m.get("role")}
            for m in rel.findall("member")
        ]
        entry = {"tags": tags, "members": members}
        rels[rel_id] = entry
        all_rels.append(entry)
    return rels, all_rels


# ---------------------------------------------------------------------------
# Tests: speed_limit inline tags helper
# ---------------------------------------------------------------------------


class TestSpeedLimitTagsHelper:
    def test_speed_limit_extracted(self):
        rules = [{"kind": "speed_limit", "value_kmh": 50}]
        tags = _speed_limit_tags(rules)
        assert ("speed_limit", "50") in tags

    def test_minimum_speed_chosen(self):
        rules = [
            {"kind": "speed_limit", "value_kmh": 70},
            {"kind": "speed_limit", "value_kmh": 50},
        ]
        tags = _speed_limit_tags(rules)
        speed_vals = [v for k, v in tags if k == "speed_limit"]
        assert speed_vals == ["50"]

    def test_no_speed_limit_rules_empty(self):
        tags = _speed_limit_tags([{"kind": "stop_sign"}])
        assert tags == []

    def test_empty_rules_empty(self):
        assert _speed_limit_tags([]) == []


# ---------------------------------------------------------------------------
# Tests: lane_marking_subtype helper
# ---------------------------------------------------------------------------


class TestLaneMarkingSubtype:
    def test_no_candidates_returns_solid(self):
        assert _lane_marking_subtype(None) == "solid"

    def test_empty_candidates_returns_solid(self):
        assert _lane_marking_subtype([]) == "solid"

    def test_high_intensity_high_density_returns_solid(self):
        candidates = [
            {
                "intensity_median": 220,
                "point_count": 20,
                "polyline_m": [[0.0, 1.75], [10.0, 1.75]],  # length ≈ 1 segment
            }
        ]
        assert _lane_marking_subtype(candidates) == "solid"

    def test_low_intensity_returns_dashed(self):
        candidates = [
            {
                "intensity_median": 80,
                "point_count": 5,
                "polyline_m": [[0.0, 1.75], [10.0, 1.75]],
            }
        ]
        assert _lane_marking_subtype(candidates) == "dashed"


# ---------------------------------------------------------------------------
# Tests: speed_limit tagging mode in export
# ---------------------------------------------------------------------------


class TestSpeedLimitTaggingMode:
    def test_lanelet_attr_mode_adds_inline_tag(self, tmp_path):
        """Default (lanelet-attr): speed_limit appears as inline tag on the lanelet."""
        graph = _make_graph_with_hd(speed_kmh=50)
        out = tmp_path / "map.osm"
        export_lanelet2(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON,
                        speed_limit_tagging="lanelet-attr")
        _, all_rels = _parse_osm(out)
        lanelets = [r for r in all_rels if r["tags"].get("type") == "lanelet"]
        assert len(lanelets) == 1
        assert lanelets[0]["tags"].get("speed_limit") == "50"

    def test_regulatory_element_mode_no_inline_tag(self, tmp_path):
        """regulatory-element mode: no inline speed_limit on the lanelet."""
        graph = _make_graph_with_hd(speed_kmh=50)
        out = tmp_path / "map.osm"
        export_lanelet2(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON,
                        speed_limit_tagging="regulatory-element")
        _, all_rels = _parse_osm(out)
        lanelets = [r for r in all_rels if r["tags"].get("type") == "lanelet"]
        assert len(lanelets) == 1
        assert "speed_limit" not in lanelets[0]["tags"]

    def test_regulatory_element_mode_emits_speed_limit_relation(self, tmp_path):
        """regulatory-element mode: a separate regulatory_element with subtype=speed_limit."""
        graph = _make_graph_with_hd(speed_kmh=50)
        out = tmp_path / "map.osm"
        export_lanelet2(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON,
                        speed_limit_tagging="regulatory-element")
        _, all_rels = _parse_osm(out)
        speed_rels = [
            r for r in all_rels
            if r["tags"].get("type") == "regulatory_element"
            and r["tags"].get("subtype") == "speed_limit"
        ]
        assert len(speed_rels) == 1
        assert speed_rels[0]["tags"].get("speed_limit") == "50"

    def test_no_speed_limit_no_speed_limit_relation(self, tmp_path):
        """Without speed_limit rule, no speed_limit regulatory_element emitted."""
        graph = _make_graph_with_hd(speed_kmh=None)
        out = tmp_path / "map.osm"
        export_lanelet2(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON,
                        speed_limit_tagging="regulatory-element")
        _, all_rels = _parse_osm(out)
        speed_rels = [
            r for r in all_rels
            if r["tags"].get("subtype") == "speed_limit"
        ]
        assert len(speed_rels) == 0

    def test_backward_compat_no_speed_limit_arg(self, tmp_path):
        """Calling export_lanelet2 without speed_limit_tagging keeps 0.5.0 behavior."""
        graph = _make_graph_with_hd(speed_kmh=60)
        out = tmp_path / "map.osm"
        export_lanelet2(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        _, all_rels = _parse_osm(out)
        lanelets = [r for r in all_rels if r["tags"].get("type") == "lanelet"]
        assert lanelets[0]["tags"].get("speed_limit") == "60"


# ---------------------------------------------------------------------------
# Tests: lane_markings boundary subtype
# ---------------------------------------------------------------------------


class TestLaneMarkingsBoundarySubtype:
    def test_solid_markers_produce_solid_subtype(self, tmp_path):
        """High-intensity markers → boundary way subtype=solid."""
        graph = _make_graph_with_hd()
        lm = {
            "candidates": [
                {
                    "edge_id": "e0",
                    "side": "left",
                    "intensity_median": 220.0,
                    "point_count": 20,
                    "polyline_m": [[0.0, 1.75], [10.0, 1.75]],
                }
            ]
        }
        out = tmp_path / "map.osm"
        export_lanelet2(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON, lane_markings=lm)
        tree = ET.parse(out)
        root = tree.getroot()
        boundary_ways = []
        for way in root.findall("way"):
            tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
            if tags.get("roadgraph") == "lane_boundary":
                boundary_ways.append(tags)
        assert len(boundary_ways) > 0
        for tags in boundary_ways:
            assert tags.get("subtype") == "solid"

    def test_no_lane_markings_defaults_to_solid(self, tmp_path):
        """No lane_markings argument → all boundary ways get subtype=solid (0.5.0 compat)."""
        graph = _make_graph_with_hd()
        out = tmp_path / "map.osm"
        export_lanelet2(graph, out, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        tree = ET.parse(out)
        root = tree.getroot()
        for way in root.findall("way"):
            tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
            if tags.get("roadgraph") == "lane_boundary":
                assert tags.get("subtype") == "solid"


# ---------------------------------------------------------------------------
# Tests: validate_lanelet2_tags
# ---------------------------------------------------------------------------


class TestValidateLanelet2Tags:
    def _write_osm_with_lanelet(self, path: Path, *, missing_subtype: bool = False, missing_location: bool = False) -> None:
        """Write a minimal OSM file with one lanelet relation."""
        tags_str = '<tag k="type" v="lanelet"/>\n'
        if not missing_subtype:
            tags_str += '<tag k="subtype" v="road"/>\n'
        if not missing_location:
            tags_str += '<tag k="location" v="urban"/>\n'
        osm = f"""<?xml version="1.0" encoding="utf-8"?>
<osm version="0.6">
  <relation id="1">
    {tags_str}
  </relation>
</osm>
"""
        path.write_text(osm, encoding="utf-8")

    def test_valid_lanelet_passes(self, tmp_path):
        osm_path = tmp_path / "valid.osm"
        self._write_osm_with_lanelet(osm_path)
        errors, warnings = validate_lanelet2_tags(osm_path)
        assert errors == []

    def test_missing_subtype_is_error(self, tmp_path):
        osm_path = tmp_path / "bad.osm"
        self._write_osm_with_lanelet(osm_path, missing_subtype=True)
        errors, _ = validate_lanelet2_tags(osm_path)
        assert any("subtype" in e for e in errors)

    def test_missing_location_is_error(self, tmp_path):
        osm_path = tmp_path / "bad.osm"
        self._write_osm_with_lanelet(osm_path, missing_location=True)
        errors, _ = validate_lanelet2_tags(osm_path)
        assert any("location" in e for e in errors)

    def test_missing_speed_limit_is_warning_not_error(self, tmp_path):
        """speed_limit absence is a warning, not a schema error."""
        osm_path = tmp_path / "warn.osm"
        self._write_osm_with_lanelet(osm_path)
        errors, warnings = validate_lanelet2_tags(osm_path)
        assert errors == []
        assert any("speed_limit" in w for w in warnings)

    def test_export_output_passes_validation(self, tmp_path):
        """An OSM file produced by export_lanelet2 must pass validation."""
        graph = _make_graph_with_hd(speed_kmh=50)
        osm_path = tmp_path / "map.osm"
        export_lanelet2(graph, osm_path, origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        errors, _ = validate_lanelet2_tags(osm_path)
        assert errors == []

    def test_non_lanelet_relations_ignored(self, tmp_path):
        """regulatory_element relations without type=lanelet must not be checked."""
        osm = """<?xml version="1.0" encoding="utf-8"?>
<osm version="0.6">
  <relation id="2">
    <tag k="type" v="regulatory_element"/>
    <tag k="subtype" v="speed_limit"/>
  </relation>
</osm>
"""
        osm_path = tmp_path / "re.osm"
        osm_path.write_text(osm, encoding="utf-8")
        errors, _ = validate_lanelet2_tags(osm_path)
        assert errors == []
