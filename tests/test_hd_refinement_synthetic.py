"""Synthetic unit tests for HD multi-source refinement (ROADMAP_0.5.md §D).

Covers:
- Each source independently produces refinement.
- Mixed sources combine correctly.
- confidence is monotonically increasing in source count and bin count.
- existing test_sd_to_hd behaviour is preserved (backward compat guard done
  in test_sd_to_hd.py; here we just test the refinement module itself).
"""

from __future__ import annotations

import pytest

from roadgraph_builder.hd.refinement import (
    EdgeHDRefinement,
    _confidence,
    refine_hd_edges,
    apply_refinements_to_graph,
)


# ---- Helpers -----------------------------------------------------------------

def _make_graph_json(edges: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "nodes": [],
        "edges": edges,
    }


def _edge(edge_id: str, trace_matched: int | None = None) -> dict:
    attrs: dict = {}
    if trace_matched is not None:
        attrs["trace_stats"] = {"matched_samples": trace_matched}
    return {"id": edge_id, "attributes": attrs}


def _lane_markings(edge_id: str, left_y: float = 1.75, right_y: float = -1.75) -> dict:
    return {
        "candidates": [
            {
                "edge_id": edge_id,
                "side": "left",
                "polyline_m": [[0.0, left_y], [10.0, left_y]],
                "intensity_median": 200.0,
                "point_count": 10,
            },
            {
                "edge_id": edge_id,
                "side": "right",
                "polyline_m": [[0.0, right_y], [10.0, right_y]],
                "intensity_median": 200.0,
                "point_count": 10,
            },
        ]
    }


class TestConfidenceFunction:
    def test_zero_sources_gives_zero(self):
        assert _confidence(0, 100) == 0.0

    def test_more_sources_gives_higher_confidence(self):
        c1 = _confidence(1, 10)
        c2 = _confidence(2, 10)
        c3 = _confidence(3, 10)
        assert 0 < c1 < c2 < c3 <= 1.0

    def test_more_bins_gives_higher_confidence(self):
        c_few = _confidence(1, 1)
        c_many = _confidence(1, 100)
        assert c_few < c_many

    def test_confidence_bounded_in_01(self):
        for n_src in range(4):
            for n_bins in (0, 1, 10, 100, 1000):
                c = _confidence(n_src, n_bins)
                assert 0.0 <= c <= 1.0, f"confidence out of range: {c} ({n_src}, {n_bins})"

    def test_monotone_in_source_count_for_various_bins(self):
        for n_bins in (0, 5, 20, 100):
            confs = [_confidence(n, n_bins) for n in range(4)]
            assert confs == sorted(confs), f"Not monotone: {confs} at n_bins={n_bins}"

    def test_monotone_in_bin_count_for_various_sources(self):
        for n_src in range(1, 4):
            confs = [_confidence(n_src, b) for b in (0, 1, 5, 10, 50, 200)]
            assert confs == sorted(confs), f"Not monotone: {confs} at n_src={n_src}"


class TestRefineHdEdgesLaneMarkingsOnly:
    def test_lane_markings_source_recognized(self):
        graph = _make_graph_json([_edge("e0")])
        lm = _lane_markings("e0", left_y=1.75, right_y=-1.75)
        results = refine_hd_edges(graph, lane_markings=lm)
        assert len(results) == 1
        r = results[0]
        assert "lane_markings" in r.sources_used

    def test_half_width_from_lane_markings_3m(self):
        graph = _make_graph_json([_edge("e0")])
        # Left at 1.5 m, right at -1.5 m → half_width = 1.5 m.
        lm = _lane_markings("e0", left_y=1.5, right_y=-1.5)
        results = refine_hd_edges(graph, lane_markings=lm, base_lane_width_m=3.5)
        r = results[0]
        assert pytest.approx(r.refined_half_width_m, abs=0.05) == 1.5

    def test_half_width_from_lane_markings_4m(self):
        graph = _make_graph_json([_edge("e0")])
        # Left at 2.0, right at -2.0 → half_width = 2.0 m (full width = 4 m).
        lm = _lane_markings("e0", left_y=2.0, right_y=-2.0)
        results = refine_hd_edges(graph, lane_markings=lm, base_lane_width_m=3.5)
        r = results[0]
        assert pytest.approx(r.refined_half_width_m, abs=0.05) == 2.0

    def test_base_half_width_preserved_in_field(self):
        graph = _make_graph_json([_edge("e0")])
        lm = _lane_markings("e0")
        results = refine_hd_edges(graph, lane_markings=lm, base_lane_width_m=3.5)
        assert pytest.approx(results[0].base_half_width_m) == 3.5 / 2.0

    def test_confidence_nonzero_when_lane_markings_present(self):
        graph = _make_graph_json([_edge("e0")])
        lm = _lane_markings("e0")
        results = refine_hd_edges(graph, lane_markings=lm)
        assert results[0].confidence > 0.0

    def test_sources_used_contains_lane_markings_not_traces(self):
        graph = _make_graph_json([_edge("e0")])  # no trace_stats
        lm = _lane_markings("e0")
        results = refine_hd_edges(graph, lane_markings=lm)
        assert "lane_markings" in results[0].sources_used
        assert "traces" not in results[0].sources_used


class TestRefineHdEdgesTracesOnly:
    def test_traces_source_recognized(self):
        graph = _make_graph_json([_edge("e0", trace_matched=20)])
        results = refine_hd_edges(graph)
        assert "traces" in results[0].sources_used

    def test_no_traces_no_source(self):
        graph = _make_graph_json([_edge("e0", trace_matched=2)])  # < 3 min
        results = refine_hd_edges(graph)
        assert "traces" not in results[0].sources_used

    def test_traces_confidence_nonzero(self):
        graph = _make_graph_json([_edge("e0", trace_matched=10)])
        results = refine_hd_edges(graph)
        assert results[0].confidence > 0.0


class TestRefineHdEdgesMixed:
    def test_two_sources_higher_confidence(self):
        graph = _make_graph_json([_edge("e0", trace_matched=10)])
        lm = _lane_markings("e0")
        results_trace_only = refine_hd_edges(graph)
        results_mixed = refine_hd_edges(graph, lane_markings=lm)
        assert results_mixed[0].confidence > results_trace_only[0].confidence

    def test_sources_used_lists_all_active(self):
        graph = _make_graph_json([_edge("e0", trace_matched=10)])
        lm = _lane_markings("e0")
        results = refine_hd_edges(graph, lane_markings=lm)
        r = results[0]
        assert "traces" in r.sources_used
        assert "lane_markings" in r.sources_used

    def test_per_edge_different_widths(self):
        """Edge A gets 3.0 m from markings, edge B gets 4.0 m."""
        graph = _make_graph_json([_edge("eA"), _edge("eB")])
        lm = {
            "candidates": [
                {
                    "edge_id": "eA",
                    "side": "left",
                    "polyline_m": [[0.0, 1.5]],
                    "intensity_median": 200.0,
                    "point_count": 5,
                },
                {
                    "edge_id": "eA",
                    "side": "right",
                    "polyline_m": [[0.0, -1.5]],
                    "intensity_median": 200.0,
                    "point_count": 5,
                },
                {
                    "edge_id": "eB",
                    "side": "left",
                    "polyline_m": [[0.0, 2.0]],
                    "intensity_median": 200.0,
                    "point_count": 5,
                },
                {
                    "edge_id": "eB",
                    "side": "right",
                    "polyline_m": [[0.0, -2.0]],
                    "intensity_median": 200.0,
                    "point_count": 5,
                },
            ]
        }
        results = refine_hd_edges(graph, lane_markings=lm)
        by_id = {r.edge_id: r for r in results}
        assert pytest.approx(by_id["eA"].refined_half_width_m, abs=0.05) == 1.5
        assert pytest.approx(by_id["eB"].refined_half_width_m, abs=0.05) == 2.0

    def test_no_sources_uses_base_width(self):
        graph = _make_graph_json([_edge("e0")])
        results = refine_hd_edges(graph, base_lane_width_m=4.0)
        r = results[0]
        assert r.sources_used == []
        assert pytest.approx(r.refined_half_width_m) == 2.0  # base 4.0 / 2
        assert r.confidence == 0.0


class TestApplyRefinementsToGraph:
    def _make_graph(self):
        from roadgraph_builder.core.graph.edge import Edge
        from roadgraph_builder.core.graph.graph import Graph
        from roadgraph_builder.core.graph.node import Node
        g = Graph(
            nodes=[Node("n0", (0.0, 0.0)), Node("n1", (10.0, 0.0))],
            edges=[
                Edge("e0", "n0", "n1", [(0.0, 0.0), (10.0, 0.0)])
            ],
        )
        return g

    def test_refinement_written_to_hd_attribute(self):
        from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
        g = self._make_graph()
        refinements = [
            EdgeHDRefinement(
                edge_id="e0",
                base_half_width_m=1.75,
                refined_half_width_m=2.0,
                centerline_offset_m=0.0,
                sources_used=["lane_markings"],
                confidence=0.5,
            )
        ]
        enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=3.5), refinements=refinements)
        hd = g.edges[0].attributes["hd"]
        assert "hd_refinement" in hd
        ref_meta = hd["hd_refinement"]
        assert ref_meta["sources_used"] == ["lane_markings"]
        assert pytest.approx(ref_meta["confidence"]) == 0.5

    def test_backward_compatible_no_refinements(self):
        """enrich_sd_to_hd with refinements=None behaves exactly as before."""
        from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
        g = self._make_graph()
        enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=3.5), refinements=None)
        hd = g.edges[0].attributes["hd"]
        assert "hd_refinement" not in hd  # untouched
        assert hd["quality"] == "centerline_offset_hd_lite"
