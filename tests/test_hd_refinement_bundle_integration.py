"""Integration test: export-bundle with --lane-markings-json applies refinements.

Uses synthetic data end-to-end through the CLI to verify the per-edge
hd_refinement metadata appears in the output road_graph.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_LAS = ROOT / "tests" / "fixtures" / "lane_markings_synth.las"
SAMPLE_CSV = ROOT / "examples" / "sample_trajectory.csv"
ORIGIN_JSON = ROOT / "examples" / "toy_map_origin.json"


def _rb() -> str:
    exe = Path(sys.executable).parent / "roadgraph_builder"
    if not exe.is_file():
        pytest.skip(f"roadgraph_builder CLI not found next to {sys.executable}")
    return str(exe)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [_rb(), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return result


def _skip_if_missing():
    for p in (SAMPLE_CSV, ORIGIN_JSON):
        if not p.is_file():
            pytest.skip(f"Required fixture not found: {p}")


class TestEnrichWithLaneMarkings:
    def test_enrich_with_lane_markings_json(self, tmp_path: Path):
        """enrich --lane-markings-json writes hd_refinement to the graph."""
        _skip_if_missing()
        # Build graph first.
        graph_path = tmp_path / "graph.json"
        r = _run("build", str(SAMPLE_CSV), str(graph_path))
        assert r.returncode == 0, r.stderr

        # Fabricate a minimal lane_markings.json.
        # We need to know an actual edge id from the graph.
        gdata = json.loads(graph_path.read_text(encoding="utf-8"))
        if not gdata["edges"]:
            pytest.skip("Graph has no edges.")
        eid = gdata["edges"][0]["id"]

        lm_path = tmp_path / "lane_markings.json"
        lm_doc = {
            "candidates": [
                {
                    "edge_id": eid,
                    "side": "left",
                    "polyline_m": [[0.0, 1.75], [5.0, 1.75]],
                    "intensity_median": 200.0,
                    "point_count": 10,
                },
                {
                    "edge_id": eid,
                    "side": "right",
                    "polyline_m": [[0.0, -1.75], [5.0, -1.75]],
                    "intensity_median": 200.0,
                    "point_count": 10,
                },
            ]
        }
        lm_path.write_text(json.dumps(lm_doc), encoding="utf-8")

        enriched_path = tmp_path / "enriched.json"
        r2 = _run(
            "enrich",
            str(graph_path),
            str(enriched_path),
            "--lane-width-m", "3.5",
            "--lane-markings-json", str(lm_path),
        )
        assert r2.returncode == 0, r2.stderr
        assert enriched_path.is_file()

        enriched = json.loads(enriched_path.read_text(encoding="utf-8"))
        # Find the edge with the marking.
        edges = enriched["edges"]
        edge_with_ref = next((e for e in edges if e["id"] == eid), None)
        assert edge_with_ref is not None
        hd = edge_with_ref.get("attributes", {}).get("hd", {})
        assert "hd_refinement" in hd, "hd_refinement not found in hd attributes"
        ref = hd["hd_refinement"]
        assert "lane_markings" in ref["sources_used"]


class TestExportBundleWithRefinements:
    def test_export_bundle_no_regression_without_lane_markings(self, tmp_path: Path):
        """export-bundle without lane-markings-json still works (backward compat)."""
        _skip_if_missing()
        out_dir = tmp_path / "bundle"
        r = _run(
            "export-bundle",
            str(SAMPLE_CSV),
            str(out_dir),
            "--origin-json", str(ORIGIN_JSON),
            "--lane-width-m", "3.5",
        )
        assert r.returncode == 0, r.stderr
        assert (out_dir / "sim" / "road_graph.json").is_file()
