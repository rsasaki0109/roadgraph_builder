"""City-scale OSM regression tests (V2).

These tests fetch real OSM data from Overpass, build a graph, export a bundle,
and assert basic sanity (edge count, no degenerate self-loops).

**They are NOT run by the default test suite.**  To run::

    pytest -m city_scale                  # run all three cities
    pytest -m city_scale -k paris         # run only the Paris test

To run in CI: use the manual ``workflow_dispatch`` trigger in
``.github/workflows/city-bench.yml``.

Overpass reliability: if the API is unreachable or returns an error, the
individual test is skipped gracefully with a diagnostic message.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# City bbox definitions
# ---------------------------------------------------------------------------
# Each entry: (name, bbox_str "min_lon,min_lat,max_lon,max_lat",
#              origin_lat, origin_lon, min_edges_expected)
_CITIES: list[tuple[str, str, float, float, int]] = [
    (
        "paris_20e",
        "2.3900,48.8450,2.4120,48.8620",
        48.8535,
        2.4010,
        100,
    ),
    (
        "tokyo_setagaya",
        "139.6200,35.6350,139.6600,35.6600",
        35.6475,
        139.6400,
        150,
    ),
    (
        "berlin_neukolln",
        "13.4150,52.4600,13.4500,52.4850",
        52.4725,
        13.4325,
        100,
    ),
]

_OVERPASS_URL = os.environ.get(
    "OVERPASS_ENDPOINT", "https://overpass-api.de/api/interpreter"
)
_USER_AGENT = (
    "roadgraph_builder/0.7-citytest (+https://github.com/rsasaki0109/roadgraph_builder)"
)
_FETCH_TIMEOUT_S = 240  # 4 minutes per city


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_overpass(bbox: str) -> dict:
    """Fetch OSM highways for bbox; return parsed JSON or raise on error."""
    # Overpass bounding box is (min_lat, min_lon, max_lat, max_lon)
    parts = bbox.split(",")
    min_lon, min_lat, max_lon, max_lat = parts
    highway_classes = (
        "motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
        "living_street|service|motorway_link|trunk_link|primary_link|"
        "secondary_link|tertiary_link"
    )
    query = f"""
[out:json][timeout:180];
(
  way["highway"~"^({highway_classes})$"]
    ({min_lat},{min_lon},{max_lat},{max_lon});
);
out body;
>;
out skel qt;
""".strip()
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        _OVERPASS_URL,
        data=body,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _count_degenerate_self_loops(graph) -> int:
    """Count edges whose start_node_id == end_node_id."""
    return sum(1 for e in graph.edges if e.start_node_id == e.end_node_id)


def _run_city_pipeline(
    name: str,
    bbox: str,
    origin_lat: float,
    origin_lon: float,
    min_edges: int,
    tmp_path: Path,
) -> None:
    """Full pipeline for one city: fetch → build → export-bundle → assert."""
    from roadgraph_builder.io.osm.graph_builder import build_graph_from_overpass_highways
    from roadgraph_builder.io.export.json_exporter import export_graph_json
    from roadgraph_builder.io.export.bundle import export_map_bundle
    import numpy as np

    # 1. Fetch
    try:
        overpass_data = _fetch_overpass(bbox)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        pytest.skip(f"Overpass unreachable ({exc!r}) — skipping {name}")

    n_elements = len(overpass_data.get("elements", []))
    if n_elements == 0:
        pytest.skip(f"Overpass returned 0 elements for {name} — likely rate-limited")

    # 2. Build graph
    t0 = time.perf_counter()
    graph = build_graph_from_overpass_highways(overpass_data, origin_lat, origin_lon)
    build_time_s = time.perf_counter() - t0

    edge_count = len(graph.edges)
    node_count = len(graph.nodes)
    selfloops = _count_degenerate_self_loops(graph)

    print(
        f"\n[{name}] OSM elements={n_elements}, "
        f"edges={edge_count}, nodes={node_count}, "
        f"self-loops={selfloops}, build={build_time_s:.1f}s"
    )

    # 3. Assertions
    assert edge_count >= min_edges, (
        f"{name}: expected ≥{min_edges} edges, got {edge_count}"
    )
    assert selfloops == 0, (
        f"{name}: {selfloops} degenerate self-loop(s) found — build pipeline regression"
    )

    # 4. Export bundle (optional artefact, stored in /tmp/)
    out_dir = tmp_path / name
    out_dir.mkdir(parents=True, exist_ok=True)

    # For OSM graphs we have no trajectory CSV; pass empty trajectory array.
    dummy_traj_xy = np.zeros((2, 2), dtype=np.float64)
    dummy_csv = out_dir / "dummy.csv"
    dummy_csv.write_text("timestamp,x,y\n0,0,0\n1,1,1\n", encoding="utf-8")

    try:
        export_map_bundle(
            graph,
            dummy_traj_xy,
            dummy_csv,
            out_dir / "bundle",
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            lane_width_m=None,  # skip HD enrich for speed
        )
        assert (out_dir / "bundle" / "manifest.json").is_file()
        assert (out_dir / "bundle" / "sim" / "road_graph.json").is_file()
    except Exception as exc:
        pytest.fail(f"{name}: export-bundle failed: {exc!r}")


# ---------------------------------------------------------------------------
# Parametrised city-scale tests
# ---------------------------------------------------------------------------


@pytest.mark.city_scale
@pytest.mark.parametrize("name,bbox,origin_lat,origin_lon,min_edges", _CITIES)
def test_city_build_and_bundle(
    name: str,
    bbox: str,
    origin_lat: float,
    origin_lon: float,
    min_edges: int,
    tmp_path: Path,
) -> None:
    """Fetch OSM, build graph, export bundle, assert sanity for one city bbox.

    Skipped gracefully when Overpass is unreachable.
    Expects: edge_count ≥ min_edges, degenerate self-loops == 0.
    """
    _run_city_pipeline(name, bbox, origin_lat, origin_lon, min_edges, tmp_path)
