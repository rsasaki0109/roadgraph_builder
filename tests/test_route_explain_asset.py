from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ASSET = ROOT / "docs" / "assets" / "route_explain_sample.json"
SCREENSHOT = ROOT / "docs" / "images" / "route_diagnostics_compare.png"


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
    assert paris_diag["expanded_states"] > astar["expanded_states"]
    assert paris_diag["queued_states"] > astar["queued_states"]
    assert paris_diag["route_edge_count"] == len(paris["edge_sequence"])


def test_route_explain_sample_is_linked_from_pages_index():
    index = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    diagnostics_js = (ROOT / "docs" / "js" / "route_diagnostics.js").read_text(
        encoding="utf-8"
    )

    assert "assets/route_explain_sample.json" in index
    assert "route --explain" in index
    assert 'id="route-diagnostics-compare"' in index
    assert 'src="js/route_diagnostics.js"' in index
    assert "Route search work is visible" in index
    assert 'fetch("assets/route_explain_sample.json")' in diagnostics_js
    assert "renderDiagnosticsComparison" in diagnostics_js


def test_route_diagnostics_preview_screenshot_is_wired():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    showcase = (ROOT / "docs" / "SHOWCASE.md").read_text(encoding="utf-8")
    preview = (ROOT / "docs" / "route_diagnostics_preview.html").read_text(
        encoding="utf-8"
    )
    script = (
        ROOT / "scripts" / "render_route_diagnostics_screenshot.py"
    ).read_text(encoding="utf-8")
    attribution = (ROOT / "docs" / "assets" / "ATTRIBUTION.md").read_text(
        encoding="utf-8"
    )

    image_ref = "docs/images/route_diagnostics_compare.png"
    assert image_ref in readme
    assert "images/route_diagnostics_compare.png" in showcase
    assert "route_diagnostics_compare.png" in attribution
    assert 'id="route-diagnostics-compare"' in preview
    assert 'src="js/route_diagnostics.js"' in preview
    assert "route_diagnostics_preview.html" in script
    assert "route_diagnostics_compare.png" in script

    data = SCREENSHOT.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert SCREENSHOT.stat().st_size < 500_000
