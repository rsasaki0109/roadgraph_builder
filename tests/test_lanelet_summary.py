"""Tests for `_emit_lanelet_summary` in scripts/refresh_docs_assets.py.

The summary JSON is what the map-console inspector reads to render its
"Lanelet2 export" card. It must agree with the actual XML so the inspector
shows truthful numbers.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
from roadgraph_builder.io.export.lanelet2 import export_lanelet2

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "refresh_docs_assets.py"
sys.path.insert(0, str(_REPO_ROOT))


def _load_refresh_module():
    spec = importlib.util.spec_from_file_location("refresh_docs_assets", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _t_junction_graph_with_elevation() -> Graph:
    g = Graph(
        nodes=[
            Node(
                id="j",
                position=(0.0, 0.0),
                attributes={
                    "junction_hint": "multi_branch",
                    "junction_type": "t_junction",
                    "degree": 3,
                    "elevation_m": 32.0,
                },
            ),
            Node(
                id="w",
                position=(-50.0, 0.0),
                attributes={"junction_hint": "dead_end", "elevation_m": 30.0},
            ),
            Node(
                id="e",
                position=(50.0, 0.0),
                attributes={"junction_hint": "dead_end", "elevation_m": 31.5},
            ),
            Node(id="s", position=(0.0, -30.0), attributes={"junction_hint": "dead_end"}),
        ],
        edges=[
            Edge(id="eW", start_node_id="w", end_node_id="j", polyline=[(-50.0, 0.0), (0.0, 0.0)], attributes={}),
            Edge(id="eE", start_node_id="j", end_node_id="e", polyline=[(0.0, 0.0), (50.0, 0.0)], attributes={}),
            Edge(id="eS", start_node_id="j", end_node_id="s", polyline=[(0.0, 0.0), (0.0, -30.0)], attributes={}),
        ],
    )
    enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=3.0))
    return g


def test_emit_lanelet_summary_counts_match_xml(tmp_path: Path) -> None:
    g = _t_junction_graph_with_elevation()
    osm_path = tmp_path / "lane.osm"
    export_lanelet2(g, osm_path, origin_lat=52.52, origin_lon=13.405)

    refresh = _load_refresh_module()
    summary_path = tmp_path / "lane_summary.json"
    refresh._emit_lanelet_summary(osm_path, summary_path)

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["format_version"] == 1
    assert payload["source_lanelet_osm"] == "lane.osm"
    assert payload["file_size_bytes"] == osm_path.stat().st_size
    # Three edges → three lanelet relations.
    assert payload["lanelet_count"] == 3
    # Bidirectional T-junction → 6 directed lane_connection pairs (no other
    # regulatory subtypes since the graph carries no semantic_rules).
    assert payload["regulatory_subtypes"] == {"lane_connection": 6}
    assert payload["regulatory_element_count"] == 6
    # Three nodes carry an `elevation_m`, so three nodes get an `ele` tag.
    assert payload["node_ele_count"] == 3
    # Every lanelet has both an outer and inner boundary; in a single-lane
    # export both are `subtype=solid`. Counts must equal lanelet_count * 2.
    boundary_total = sum(payload["boundary_subtypes"].values())
    assert boundary_total == payload["lanelet_count"] * 2


def test_emit_lanelet_summary_skips_when_path_missing(tmp_path: Path) -> None:
    refresh = _load_refresh_module()
    summary_path = tmp_path / "missing_summary.json"
    refresh._emit_lanelet_summary(tmp_path / "nope.osm", summary_path)
    assert not summary_path.exists()


def test_committed_lanelet_summaries_match_committed_xml(tmp_path: Path) -> None:
    """The committed `docs/assets/*_lanelet_summary.json` must agree with the
    committed `docs/assets/*.lanelet.osm` they describe — otherwise the map
    console renders stale numbers and the inspector lies to visitors.
    """
    refresh = _load_refresh_module()
    assets = _REPO_ROOT / "docs" / "assets"
    datasets = ["map_paris_grid", "map_berlin_mitte", "map_tokyo_ginza"]
    for stem in datasets:
        osm_path = assets / f"{stem}.lanelet.osm"
        committed_summary_path = assets / f"{stem}_lanelet_summary.json"
        if not osm_path.is_file() or not committed_summary_path.is_file():
            continue
        regen_path = tmp_path / f"{stem}_summary.json"
        refresh._emit_lanelet_summary(osm_path, regen_path)
        committed = json.loads(committed_summary_path.read_text(encoding="utf-8"))
        regen = json.loads(regen_path.read_text(encoding="utf-8"))
        assert committed == regen, (
            f"{committed_summary_path.name} is stale relative to "
            f"{osm_path.name} — re-run scripts/refresh_docs_assets.py "
            "(or the lanelet emitter)"
        )
