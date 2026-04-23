from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ASSET = ROOT / "docs" / "assets" / "map_match_explain_sample.json"


def test_map_match_explain_sample_asset_has_expected_diagnostics():
    doc = json.loads(ASSET.read_text(encoding="utf-8"))

    assert doc["schema_version"] == 1
    assert doc["generated_by"] == "scripts/refresh_docs_assets.py"
    assert doc["source_graph"] == "examples/frozen_bundle/sim/road_graph.json"
    assert doc["source_trajectory"] == "examples/sample_trajectory.csv"

    samples = {sample["id"]: sample for sample in doc["samples"]}
    assert set(samples) == {"toy_nearest_edge", "toy_hmm_viterbi"}

    nearest = samples["toy_nearest_edge"]
    nearest_stats = nearest["result"]["stats"]
    nearest_diag = nearest_stats["diagnostics"]
    assert "--explain" in nearest["command"]
    assert nearest_stats["algorithm"] == "nearest_edge"
    assert nearest_stats["matched"] == 8
    assert nearest_diag["projection_queries"] == 8
    assert nearest_diag["edge_index"]["enabled"] is True
    assert nearest_diag["edge_index"]["segment_count"] == 2
    assert nearest_diag["edge_index"]["overflow_segment_count"] == 0

    hmm = samples["toy_hmm_viterbi"]
    hmm_stats = hmm["result"]["stats"]
    hmm_diag = hmm_stats["diagnostics"]
    assert "--hmm" in hmm["command"]
    assert "--explain" in hmm["command"]
    assert hmm_stats["algorithm"] == "hmm_viterbi"
    assert hmm_stats["matched"] == 8
    assert hmm_diag["candidate_queries"] == 8
    assert hmm_diag["candidate_limit_per_sample"] == 5
    assert hmm_diag["edge_index"]["segment_count"] == 2


def test_map_match_explain_sample_is_linked_from_docs():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    showcase = (ROOT / "docs" / "SHOWCASE.md").read_text(encoding="utf-8")
    attribution = (ROOT / "docs" / "assets" / "ATTRIBUTION.md").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "scripts" / "refresh_docs_assets.py").read_text(encoding="utf-8")

    assert "docs/assets/map_match_explain_sample.json" in readme
    assert "assets/map_match_explain_sample.json" in showcase
    assert "map_match_explain_sample.json" in attribution
    assert "_write_map_match_explain_sample_asset" in script
