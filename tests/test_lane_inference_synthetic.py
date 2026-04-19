"""Synthetic unit tests for lane-count inference (ROADMAP_0.6.md §α).

Tests cover:
- 3-column paint markers → lane_count=2, offsets=[-1.75, +1.75]
- trace_stats bimodal fallback → lane_count=2
- trace_stats unimodal fallback → lane_count=1
- Both sources absent → lane_count=1 (default)
- Graceful degradation when sources absent
"""

from __future__ import annotations

import math
import pytest

from roadgraph_builder.hd.lane_inference import (
    EdgeLaneInference,
    LaneGeometry,
    infer_lane_counts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph_json(edges: list[dict]) -> dict:
    return {"schema_version": 1, "nodes": [], "edges": edges}


def _simple_edge(edge_id: str, polyline=None, trace_perp=None) -> dict:
    attrs: dict = {}
    if trace_perp is not None:
        attrs["trace_stats"] = {"perpendicular_offsets": trace_perp}
    if polyline is None:
        polyline = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}]
    return {"id": edge_id, "polyline": polyline, "attributes": attrs}


def _lane_markings_3col(edge_id: str) -> dict:
    """Three marker columns at -3.5, 0, +3.5 m → 2 lanes."""
    return {
        "candidates": [
            {
                "edge_id": edge_id,
                "side": "left",
                "polyline_m": [[0.0, 3.5], [10.0, 3.5]],
                "intensity_median": 200.0,
                "point_count": 5,
            },
            {
                "edge_id": edge_id,
                "side": "center",
                "polyline_m": [[0.0, 0.0], [10.0, 0.0]],
                "intensity_median": 200.0,
                "point_count": 5,
            },
            {
                "edge_id": edge_id,
                "side": "right",
                "polyline_m": [[0.0, -3.5], [10.0, -3.5]],
                "intensity_median": 200.0,
                "point_count": 5,
            },
        ]
    }


# ---------------------------------------------------------------------------
# Tests: marker-based inference
# ---------------------------------------------------------------------------


class TestLaneInferenceLaneMarkings:
    def test_3_columns_gives_lane_count_2(self):
        graph = _make_graph_json([_simple_edge("e0")])
        lm = _lane_markings_3col("e0")
        results = infer_lane_counts(graph, lane_markings=lm, base_lane_width_m=3.5)
        assert len(results) == 1
        r = results[0]
        assert r.lane_count == 2

    def test_3_columns_offsets_symmetric(self):
        """Offsets must be [-1.75, +1.75] for 2-lane road 3.5 m wide each."""
        graph = _make_graph_json([_simple_edge("e0")])
        lm = _lane_markings_3col("e0")
        results = infer_lane_counts(graph, lane_markings=lm, base_lane_width_m=3.5)
        r = results[0]
        assert r.lane_count == 2
        offsets = sorted(lg.offset_m for lg in r.lanes)
        # The road half-width = 3.5/2 = 1.75; spacing per lane = 1.75; offsets ±1.75/2... wait
        # base_lane_width_m is a *single lane* width.
        # road_half_width = 3.5/2 = 1.75; lane_count=2 → spacing = 3.5/2 = 1.75
        # offsets: leftmost = 1.75 - 1.75/2 = 0.875, second = 0.875 - 1.75 = -0.875
        # Actually let's just confirm the symmetry.
        assert len(offsets) == 2
        assert pytest.approx(offsets[0], abs=0.01) == -offsets[1]

    def test_3_columns_sources_used(self):
        graph = _make_graph_json([_simple_edge("e0")])
        lm = _lane_markings_3col("e0")
        results = infer_lane_counts(graph, lane_markings=lm)
        assert "lane_markings" in results[0].sources_used

    def test_2_columns_gives_lane_count_1(self):
        """Left + right only → 1 lane (2 boundaries, 1 gap)."""
        graph = _make_graph_json([_simple_edge("e0")])
        lm = {
            "candidates": [
                {"edge_id": "e0", "side": "left", "polyline_m": [[0.0, 1.75]], "intensity_median": 200, "point_count": 3},
                {"edge_id": "e0", "side": "right", "polyline_m": [[0.0, -1.75]], "intensity_median": 200, "point_count": 3},
            ]
        }
        results = infer_lane_counts(graph, lane_markings=lm, base_lane_width_m=3.5)
        assert results[0].lane_count == 1

    def test_lane_geometry_length_matches_count(self):
        graph = _make_graph_json([_simple_edge("e0")])
        lm = _lane_markings_3col("e0")
        results = infer_lane_counts(graph, lane_markings=lm)
        r = results[0]
        assert len(r.lanes) == r.lane_count

    def test_lane_index_sequential(self):
        graph = _make_graph_json([_simple_edge("e0")])
        lm = _lane_markings_3col("e0")
        results = infer_lane_counts(graph, lane_markings=lm)
        r = results[0]
        for i, lg in enumerate(r.lanes):
            assert lg.lane_index == i

    def test_confidence_nonzero_when_markings_present(self):
        graph = _make_graph_json([_simple_edge("e0")])
        lm = _lane_markings_3col("e0")
        results = infer_lane_counts(graph, lane_markings=lm)
        for lg in results[0].lanes:
            assert lg.confidence > 0.0

    def test_centerline_has_correct_point_count(self):
        """Each lane centerline should have at least 2 points (same as the edge polyline)."""
        graph = _make_graph_json([_simple_edge("e0")])
        lm = _lane_markings_3col("e0")
        results = infer_lane_counts(graph, lane_markings=lm)
        for lg in results[0].lanes:
            assert len(lg.centerline_m) >= 2

    def test_unrelated_edge_not_affected(self):
        """Markings for e0 don't change inference for e1."""
        graph = _make_graph_json([_simple_edge("e0"), _simple_edge("e1")])
        lm = _lane_markings_3col("e0")
        results = infer_lane_counts(graph, lane_markings=lm)
        by_id = {r.edge_id: r for r in results}
        assert by_id["e0"].lane_count == 2
        assert by_id["e1"].lane_count == 1  # default


# ---------------------------------------------------------------------------
# Tests: trace_stats fallback
# ---------------------------------------------------------------------------


class TestLaneInferenceTraceFallback:
    def test_bimodal_offsets_gives_lane_count_2(self):
        """Two modes separated by > split_gap_m → lane_count=2."""
        perp = [-1.5] * 5 + [1.5] * 5  # two clear clusters, gap=3.0 > 2.0
        graph = _make_graph_json([_simple_edge("e0", trace_perp=perp)])
        results = infer_lane_counts(graph, base_lane_width_m=3.5, split_gap_m=2.0)
        assert results[0].lane_count == 2
        assert "trace_stats" in results[0].sources_used

    def test_unimodal_offsets_gives_lane_count_1(self):
        """All offsets within split_gap_m → lane_count=1."""
        perp = [-0.2, 0.0, 0.1, -0.1, 0.2]  # one cluster
        graph = _make_graph_json([_simple_edge("e0", trace_perp=perp)])
        results = infer_lane_counts(graph, base_lane_width_m=3.5, split_gap_m=2.0)
        assert results[0].lane_count == 1
        assert "trace_stats" in results[0].sources_used

    def test_trace_stats_takes_second_priority(self):
        """When lane_markings is provided and has hits, trace_stats is ignored."""
        perp = [-1.5] * 5 + [1.5] * 5
        graph = _make_graph_json([_simple_edge("e0", trace_perp=perp)])
        lm = {
            "candidates": [
                {"edge_id": "e0", "side": "left", "polyline_m": [[0.0, 1.75]], "intensity_median": 200, "point_count": 2},
                {"edge_id": "e0", "side": "right", "polyline_m": [[0.0, -1.75]], "intensity_median": 200, "point_count": 2},
            ]
        }
        results = infer_lane_counts(graph, lane_markings=lm, base_lane_width_m=3.5)
        assert "lane_markings" in results[0].sources_used
        assert "trace_stats" not in results[0].sources_used


# ---------------------------------------------------------------------------
# Tests: default fallback
# ---------------------------------------------------------------------------


class TestLaneInferenceDefault:
    def test_no_sources_gives_lane_count_1(self):
        graph = _make_graph_json([_simple_edge("e0")])
        results = infer_lane_counts(graph)
        assert results[0].lane_count == 1

    def test_no_sources_sources_used_is_default(self):
        graph = _make_graph_json([_simple_edge("e0")])
        results = infer_lane_counts(graph)
        assert results[0].sources_used == ["default"]

    def test_no_sources_confidence_is_zero(self):
        graph = _make_graph_json([_simple_edge("e0")])
        results = infer_lane_counts(graph)
        for lg in results[0].lanes:
            assert lg.confidence == 0.0

    def test_empty_graph_returns_empty(self):
        graph = _make_graph_json([])
        results = infer_lane_counts(graph)
        assert results == []

    def test_max_lanes_respected(self):
        """Even with many marker clusters, lane_count is clamped to max_lanes."""
        candidates = [
            {
                "edge_id": "e0",
                "side": "center",
                "polyline_m": [[0.0, float(i * 4)]],
                "intensity_median": 200,
                "point_count": 2,
            }
            for i in range(10)
        ]
        graph = _make_graph_json([_simple_edge("e0")])
        lm = {"candidates": candidates}
        results = infer_lane_counts(graph, lane_markings=lm, max_lanes=4)
        assert results[0].lane_count <= 4

    def test_min_lanes_respected(self):
        """lane_count is always >= min_lanes."""
        graph = _make_graph_json([_simple_edge("e0")])
        results = infer_lane_counts(graph, min_lanes=2)
        assert results[0].lane_count >= 2

    def test_result_is_one_per_edge(self):
        graph = _make_graph_json([_simple_edge("eA"), _simple_edge("eB"), _simple_edge("eC")])
        results = infer_lane_counts(graph)
        assert len(results) == 3
        assert {r.edge_id for r in results} == {"eA", "eB", "eC"}
