from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ASSET = ROOT / "docs" / "assets" / "route_explain_sample.json"


def test_route_explain_sample_asset_has_expected_diagnostics():
    doc = json.loads(ASSET.read_text(encoding="utf-8"))

    assert doc["schema_version"] == 1
    assert "OpenStreetMap" in doc["attribution"]
    assert doc["license_url"] == "https://opendatacommons.org/licenses/odbl/1-0/"

    samples = {sample["id"]: sample for sample in doc["samples"]}
    assert set(samples) == {"metric_sample_astar", "paris_grid_dijkstra_fallback"}

    astar = samples["metric_sample_astar"]["diagnostics"]
    assert astar["search_engine"] == "astar"
    assert astar["heuristic_enabled"] is True
    assert astar["fallback_reason"] is None
    assert astar["expanded_states"] > 0
    assert astar["queued_states"] >= astar["expanded_states"]

    paris = samples["paris_grid_dijkstra_fallback"]
    paris_diag = paris["diagnostics"]
    assert paris["applied_restrictions"] == 10
    assert paris_diag["search_engine"] == "dijkstra"
    assert paris_diag["heuristic_enabled"] is False
    assert paris_diag["fallback_reason"] == "non_metric_geometry"
    assert paris_diag["route_edge_count"] == len(paris["edge_sequence"])


def test_route_explain_sample_is_linked_from_pages_index():
    index = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "assets/route_explain_sample.json" in index
    assert "route --explain" in index
