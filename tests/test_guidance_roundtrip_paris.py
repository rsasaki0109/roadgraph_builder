"""End-to-end guidance test using the Paris grid assets (if present).

Falls back gracefully when the Paris assets aren't in the working tree,
so CI without the optional assets still passes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PARIS_ROUTE = ROOT / "docs" / "assets" / "route_paris_grid.geojson"
PARIS_SD_NAV = ROOT / "docs" / "assets"  # sd_nav is NOT in assets; use bundle path
# The Paris grid sd_nav is in the bundle, not in docs/assets — we'll construct
# a minimal sd_nav from the route geojson alone.


@pytest.fixture
def paris_route_geojson():
    if not PARIS_ROUTE.is_file():
        pytest.skip(f"Paris route GeoJSON not found: {PARIS_ROUTE}")
    return json.loads(PARIS_ROUTE.read_text(encoding="utf-8"))


def test_paris_guidance_sequence_order(paris_route_geojson):
    """First step is depart, last step is arrive, steps are indexed 0..N-1."""
    from roadgraph_builder.navigation.guidance import build_guidance

    empty_sd_nav = {"edges": []}
    steps = build_guidance(paris_route_geojson, empty_sd_nav)
    if not steps:
        pytest.skip("No edge features found in Paris route GeoJSON.")

    assert steps[0].maneuver_at_end == "depart"
    assert steps[-1].maneuver_at_end == "arrive"
    assert all(s.step_index == i for i, s in enumerate(steps))


def test_paris_guidance_cumulative_distance_increases(paris_route_geojson):
    from roadgraph_builder.navigation.guidance import build_guidance

    steps = build_guidance(paris_route_geojson, {"edges": []})
    if len(steps) < 2:
        pytest.skip("Need at least 2 steps.")
    distances = [s.start_distance_m for s in steps]
    for i in range(1, len(distances)):
        assert distances[i] >= distances[i - 1], f"Distance not monotone at step {i}"


def test_paris_guidance_all_maneuvers_valid(paris_route_geojson):
    from roadgraph_builder.navigation.guidance import build_guidance, MANEUVER_CATEGORIES

    steps = build_guidance(paris_route_geojson, {"edges": []})
    for s in steps:
        assert s.maneuver_at_end in MANEUVER_CATEGORIES, (
            f"Step {s.step_index} has invalid maneuver: {s.maneuver_at_end!r}"
        )


def test_paris_guidance_schema_validates(paris_route_geojson):
    from roadgraph_builder.navigation.guidance import build_guidance
    from roadgraph_builder.validation import validate_guidance_document

    steps = build_guidance(paris_route_geojson, {"edges": []})
    doc = {
        "steps": [
            {
                "step_index": s.step_index,
                "edge_id": s.edge_id,
                "start_distance_m": s.start_distance_m,
                "length_m": s.length_m,
                "maneuver_at_end": s.maneuver_at_end,
                "heading_change_deg": s.heading_change_deg,
                "junction_type_at_end": s.junction_type_at_end,
                "description": s.description,
                "sd_nav_edge_maneuvers": s.sd_nav_edge_maneuvers,
            }
            for s in steps
        ]
    }
    validate_guidance_document(doc)  # Should not raise.
