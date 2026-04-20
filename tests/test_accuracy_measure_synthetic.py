"""Synthetic unit tests for scripts/measure_lane_accuracy.py (V1).

Tests cover:
- Perfect prediction (all lanes match) → MAE = 0.
- All wrong by 1 → MAE = 1.
- Confusion matrix counts are correct.
- Distance filtering rejects far-away OSM ways.
- Alignment filtering rejects perpendicular ways.
- Unmatched edges (no OSM counterpart within tolerance) counted correctly.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Import measure_lane_accuracy directly from the script.
import importlib.util

_SCRIPT = _REPO_ROOT / "scripts" / "measure_lane_accuracy.py"
_spec = importlib.util.spec_from_file_location("measure_lane_accuracy", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[attr-defined]

measure_lane_accuracy = _mod.measure_lane_accuracy


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_graph(edges: list[dict]) -> dict:
    """Minimal graph JSON with given edges."""
    return {"schema_version": 1, "nodes": [], "edges": edges}


def _make_edge(
    eid: str,
    cx: float,
    cy: float,
    lane_count: int,
    length: float = 100.0,
    direction: str = "east",
) -> dict:
    """Build a graph edge with a predicted lane_count and a simple horizontal polyline."""
    if direction == "east":
        polyline = [
            {"x": cx - length / 2, "y": cy},
            {"x": cx + length / 2, "y": cy},
        ]
    else:  # north
        polyline = [
            {"x": cx, "y": cy - length / 2},
            {"x": cx, "y": cy + length / 2},
        ]
    return {
        "id": eid,
        "start_node_id": "n0",
        "end_node_id": "n1",
        "polyline": polyline,
        "attributes": {
            "kind": "lane_centerline",
            "hd": {"lane_count": lane_count},
        },
    }


def _make_osm(
    ways: list[dict],
    nodes: list[dict] | None = None,
) -> dict:
    """Build a minimal Overpass-style JSON with the given way and node elements."""
    elements: list[dict] = []
    if nodes:
        elements.extend(nodes)
    elements.extend(ways)
    return {"version": 0.6, "elements": elements}


def _way_and_nodes(
    wid: int,
    cx: float,
    cy: float,
    lanes: int,
    length: float = 100.0,
    direction: str = "east",
) -> tuple[dict, list[dict]]:
    """Return (way_element, [node_elements]) for an OSM way centred at (cx, cy)."""
    if direction == "east":
        n1 = {"id": wid * 100 + 1, "type": "node", "lat": cy, "lon": cx - length / 2}
        n2 = {"id": wid * 100 + 2, "type": "node", "lat": cy, "lon": cx + length / 2}
    else:  # north
        n1 = {"id": wid * 100 + 1, "type": "node", "lat": cy - length / 2, "lon": cx}
        n2 = {"id": wid * 100 + 2, "type": "node", "lat": cy + length / 2, "lon": cx}
    way = {
        "id": wid,
        "type": "way",
        "nodes": [n1["id"], n2["id"]],
        "tags": {"highway": "residential", "lanes": str(lanes)},
    }
    return way, [n1, n2]


# ---------------------------------------------------------------------------
# Tests: perfect match
# ---------------------------------------------------------------------------


class TestMeasureLaneAccuracySynthetic:
    def test_perfect_match_mae_is_zero(self) -> None:
        """When predicted == actual for every matched edge, MAE = 0."""
        # Graph: two edges, both 2 lanes, at (0.001, 0.001) and (0.002, 0.001).
        graph = _make_graph(
            [
                _make_edge("e0", 0.001, 0.001, lane_count=2),
                _make_edge("e1", 0.002, 0.001, lane_count=2),
            ]
        )
        w0, n0 = _way_and_nodes(1, 0.001, 0.001, lanes=2)
        w1, n1 = _way_and_nodes(2, 0.002, 0.001, lanes=2)
        osm = _make_osm([w0, w1], nodes=n0 + n1)

        result = measure_lane_accuracy(
            graph, osm, matching_tolerance_m=5000.0, use_haversine=True
        )
        assert result["mae"] == pytest.approx(0.0), f"MAE should be 0, got {result['mae']}"
        assert result["matched_count"] == 2
        assert result["unmatched_count"] == 0

    def test_all_off_by_one_mae_is_one(self) -> None:
        """When every prediction is off by 1, MAE = 1.0."""
        graph = _make_graph(
            [
                _make_edge("e0", 0.001, 0.001, lane_count=2),
                _make_edge("e1", 0.002, 0.001, lane_count=1),
            ]
        )
        # Actual: 1 and 2 respectively → errors = |2-1|=1 and |1-2|=1 → MAE=1.
        w0, n0 = _way_and_nodes(1, 0.001, 0.001, lanes=1)
        w1, n1 = _way_and_nodes(2, 0.002, 0.001, lanes=2)
        osm = _make_osm([w0, w1], nodes=n0 + n1)

        result = measure_lane_accuracy(
            graph, osm, matching_tolerance_m=5000.0, use_haversine=True
        )
        assert result["mae"] == pytest.approx(1.0, abs=1e-9)
        assert result["matched_count"] == 2

    def test_confusion_matrix_counts(self) -> None:
        """Confusion matrix accumulates correctly."""
        # Three edges: predicted=[1,2,2], actual=[1,1,2]
        graph = _make_graph(
            [
                _make_edge("e0", 0.001, 0.001, lane_count=1),
                _make_edge("e1", 0.002, 0.001, lane_count=2),
                _make_edge("e2", 0.003, 0.001, lane_count=2),
            ]
        )
        w0, n0 = _way_and_nodes(1, 0.001, 0.001, lanes=1)
        w1, n1 = _way_and_nodes(2, 0.002, 0.001, lanes=1)
        w2, n2 = _way_and_nodes(3, 0.003, 0.001, lanes=2)
        osm = _make_osm([w0, w1, w2], nodes=n0 + n1 + n2)

        result = measure_lane_accuracy(
            graph, osm, matching_tolerance_m=5000.0, use_haversine=True
        )
        cm = result["confusion_matrix"]
        # actual=1, predicted=1 → count=1
        assert cm.get("1", {}).get("1", 0) == 1
        # actual=1, predicted=2 → count=1
        assert cm.get("1", {}).get("2", 0) == 1
        # actual=2, predicted=2 → count=1
        assert cm.get("2", {}).get("2", 0) == 1
        assert result["matched_count"] == 3

    def test_distance_filter_rejects_far_ways(self) -> None:
        """Ways beyond matching_tolerance_m are not matched."""
        graph = _make_graph([_make_edge("e0", 0.001, 0.001, lane_count=2)])
        # Place OSM way far away (0.1 deg ≈ ~11 km, well beyond 5 m tolerance).
        w, n = _way_and_nodes(1, 0.101, 0.001, lanes=2)
        osm = _make_osm([w], nodes=n)

        result = measure_lane_accuracy(
            graph, osm, matching_tolerance_m=5.0, use_haversine=True
        )
        assert result["matched_count"] == 0
        assert result["unmatched_count"] == 1

    def test_alignment_filter_rejects_perpendicular(self) -> None:
        """A perpendicular OSM way is rejected even if within distance."""
        # Edge goes east; OSM way goes north.
        graph = _make_graph([_make_edge("e0", 0.001, 0.001, lane_count=2, direction="east")])
        # Make way share the same centroid but run north-south.
        w, n = _way_and_nodes(1, 0.001, 0.001, lanes=2, direction="north")
        osm = _make_osm([w], nodes=n)

        result = measure_lane_accuracy(
            graph, osm, matching_tolerance_m=5000.0, min_alignment_cos=0.7, use_haversine=True
        )
        # cos(90°) = 0 < 0.7 → rejected.
        assert result["matched_count"] == 0
        assert result["unmatched_count"] == 1

    def test_alignment_accepts_parallel_way(self) -> None:
        """A parallel OSM way is matched."""
        graph = _make_graph([_make_edge("e0", 0.001, 0.001, lane_count=2, direction="east")])
        w, n = _way_and_nodes(1, 0.001, 0.001, lanes=2, direction="east")
        osm = _make_osm([w], nodes=n)

        result = measure_lane_accuracy(
            graph, osm, matching_tolerance_m=5000.0, min_alignment_cos=0.7, use_haversine=True
        )
        assert result["matched_count"] == 1

    def test_no_osm_lanes_tag_way_ignored(self) -> None:
        """OSM ways without lanes= tag are not used as ground truth."""
        graph = _make_graph([_make_edge("e0", 0.001, 0.001, lane_count=2)])
        # Way without lanes= tag.
        n1 = {"id": 101, "type": "node", "lat": 0.001, "lon": 0.0005}
        n2 = {"id": 102, "type": "node", "lat": 0.001, "lon": 0.0015}
        w = {"id": 1, "type": "way", "nodes": [101, 102], "tags": {"highway": "residential"}}
        osm = _make_osm([w], nodes=[n1, n2])

        result = measure_lane_accuracy(
            graph, osm, matching_tolerance_m=5000.0, use_haversine=True
        )
        assert result["matched_count"] == 0
        assert result["unmatched_count"] == 1

    def test_mae_formula(self) -> None:
        """MAE = mean(|pred - actual|) across matched pairs."""
        # Three pairs: errors = [0, 1, 2]  → MAE = 1.0
        graph = _make_graph(
            [
                _make_edge("e0", 0.001, 0.001, lane_count=2),
                _make_edge("e1", 0.002, 0.001, lane_count=2),
                _make_edge("e2", 0.003, 0.001, lane_count=4),
            ]
        )
        w0, n0 = _way_and_nodes(1, 0.001, 0.001, lanes=2)  # error = 0
        w1, n1 = _way_and_nodes(2, 0.002, 0.001, lanes=1)  # error = 1
        w2, n2 = _way_and_nodes(3, 0.003, 0.001, lanes=2)  # error = 2
        osm = _make_osm([w0, w1, w2], nodes=n0 + n1 + n2)

        result = measure_lane_accuracy(
            graph, osm, matching_tolerance_m=5000.0, use_haversine=True
        )
        assert result["matched_count"] == 3
        expected_mae = (0 + 1 + 2) / 3
        assert result["mae"] == pytest.approx(expected_mae, abs=1e-9)

    def test_empty_graph_no_crash(self) -> None:
        """Empty graph returns matched_count=0, mae=None."""
        graph = _make_graph([])
        w, n = _way_and_nodes(1, 0.001, 0.001, lanes=2)
        osm = _make_osm([w], nodes=n)

        result = measure_lane_accuracy(graph, osm, matching_tolerance_m=5000.0)
        assert result["matched_count"] == 0
        assert result["mae"] is None

    def test_empty_osm_all_unmatched(self) -> None:
        """When OSM has no usable ways, all edges are unmatched."""
        graph = _make_graph([_make_edge("e0", 0.001, 0.001, lane_count=2)])
        osm = _make_osm([])

        result = measure_lane_accuracy(graph, osm, matching_tolerance_m=5000.0)
        assert result["matched_count"] == 0
        assert result["unmatched_count"] == 1

    def test_map_origin_converts_osm_to_meter_frame(self) -> None:
        """When graph.metadata.map_origin is present, OSM lon/lat gets converted
        to the same local meter frame; a 5 m tolerance then works against a
        meter-frame graph polyline."""
        # Edge polyline in meters, centered at (0, 0) running east.
        edge = {
            "id": "e0",
            "start_node_id": "n0",
            "end_node_id": "n1",
            "polyline": [{"x": -50.0, "y": 0.0}, {"x": 50.0, "y": 0.0}],
            "attributes": {"kind": "lane_centerline", "hd": {"lane_count": 2}},
        }
        graph = {
            "schema_version": 1,
            "nodes": [],
            "edges": [edge],
            "metadata": {"map_origin": {"lat0": 35.67, "lon0": 139.768}},
        }
        # OSM way centered exactly at origin (35.67, 139.768) going east.
        # Offset by ~0.0009 deg ≈ 100 m east/west for the two endpoints.
        n1 = {"id": 101, "type": "node", "lat": 35.67, "lon": 139.768 - 0.000449}
        n2 = {"id": 102, "type": "node", "lat": 35.67, "lon": 139.768 + 0.000449}
        way = {
            "id": 1,
            "type": "way",
            "nodes": [101, 102],
            "tags": {"highway": "secondary", "lanes": "2"},
        }
        osm = {"version": 0.6, "elements": [n1, n2, way]}

        # 5 m tolerance works because both sides now live in meters.
        result = measure_lane_accuracy(graph, osm, matching_tolerance_m=5.0)
        assert result["matched_count"] == 1
        assert result["pairs"][0]["predicted"] == 2
        assert result["pairs"][0]["actual"] == 2
        assert result["pairs"][0]["distance_m"] < 5.0
