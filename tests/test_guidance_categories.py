"""Unit tests for guidance.py: maneuver category boundary values and sequences.

Tests the categorize_maneuver boundaries, the L-shaped route (right turn),
the symmetric left turn, sequence order (depart→...→arrive), and heading sign.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from roadgraph_builder.navigation.guidance import (
    MANEUVER_CATEGORIES,
    GuidanceStep,
    build_guidance,
)


def _make_edge_feature(
    edge_id: str,
    coords: list[list[float]],
    length_m: float = 10.0,
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {
            "kind": "route_edge",
            "edge_id": edge_id,
            "length_m": length_m,
        },
        "geometry": {
            "type": "LineString",
            "coordinates": coords,
        },
    }


def _make_route(edge_features: list[dict]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": edge_features,
    }


EMPTY_SD_NAV: dict[str, Any] = {"edges": []}


class TestManeuverCategories:
    """Test the MANEUVER_CATEGORIES constant is complete."""

    def test_all_expected_categories_present(self):
        expected = {
            "depart", "arrive", "straight",
            "slight_left", "left", "sharp_left",
            "slight_right", "right", "sharp_right",
            "u_turn", "continue",
        }
        assert set(MANEUVER_CATEGORIES) == expected


class TestSingleEdgeRoute:
    """A single-edge route = depart only (edge IS the destination)."""

    def test_single_edge_depart(self):
        route = _make_route([
            _make_edge_feature("e0", [[0, 0], [10, 0]])
        ])
        steps = build_guidance(route, EMPTY_SD_NAV)
        # With one edge, only "depart" (first) is emitted;
        # but since it's both first and last, it could be either.
        # Per our implementation: first edge = depart.
        assert len(steps) == 1
        assert steps[0].maneuver_at_end == "depart"

    def test_empty_route(self):
        route = _make_route([])
        steps = build_guidance(route, EMPTY_SD_NAV)
        assert steps == []


class TestSequenceOrder:
    """Verify depart → ... → arrive sequence ordering."""

    def test_depart_arrive_order_three_edges(self):
        route = _make_route([
            _make_edge_feature("e0", [[0, 0], [10, 0]]),
            _make_edge_feature("e1", [[10, 0], [20, 0]]),
            _make_edge_feature("e2", [[20, 0], [30, 0]]),
        ])
        steps = build_guidance(route, EMPTY_SD_NAV)
        assert steps[0].maneuver_at_end == "depart"
        assert steps[-1].maneuver_at_end == "arrive"
        assert all(s.step_index == i for i, s in enumerate(steps))

    def test_cumulative_distance_monotone(self):
        route = _make_route([
            _make_edge_feature("e0", [[0, 0], [10, 0]], length_m=10.0),
            _make_edge_feature("e1", [[10, 0], [20, 0]], length_m=10.0),
            _make_edge_feature("e2", [[20, 0], [30, 0]], length_m=10.0),
        ])
        steps = build_guidance(route, EMPTY_SD_NAV)
        distances = [s.start_distance_m for s in steps]
        assert distances == sorted(distances)
        assert distances[0] == 0.0
        assert distances[1] == pytest.approx(10.0)
        assert distances[2] == pytest.approx(20.0)


class TestLShapeRoute:
    """Synthetic L-shaped route: straight then right turn at 90 degrees."""

    def _right_turn_route(self) -> dict[str, Any]:
        # Edge 0: goes East (along +x).
        # Edge 1: turns South (along -y) — a right turn.
        # Edge 2: continues South.
        return _make_route([
            _make_edge_feature("e0", [[0, 0], [10, 0]], length_m=10.0),
            _make_edge_feature("e1", [[10, 0], [10, -10]], length_m=10.0),
            _make_edge_feature("e2", [[10, -10], [10, -20]], length_m=10.0),
        ])

    def _left_turn_route(self) -> dict[str, Any]:
        # Edge 0: goes East (along +x).
        # Edge 1: turns North (along +y) — a left turn.
        # Edge 2: continues North.
        return _make_route([
            _make_edge_feature("e0", [[0, 0], [10, 0]], length_m=10.0),
            _make_edge_feature("e1", [[10, 0], [10, 10]], length_m=10.0),
            _make_edge_feature("e2", [[10, 10], [10, 20]], length_m=10.0),
        ])

    def test_right_turn_maneuver(self):
        steps = build_guidance(self._right_turn_route(), EMPTY_SD_NAV)
        # Step 1 (index 1, middle) is the turning step.
        mid = steps[1]
        assert mid.maneuver_at_end == "right", (
            f"Expected 'right', got '{mid.maneuver_at_end}' (heading={mid.heading_change_deg:.1f}°)"
        )

    def test_right_turn_heading_close_to_90(self):
        steps = build_guidance(self._right_turn_route(), EMPTY_SD_NAV)
        mid = steps[1]
        assert abs(mid.heading_change_deg - 90.0) < 2.0, (
            f"Expected ~+90°, got {mid.heading_change_deg:.2f}°"
        )

    def test_left_turn_maneuver(self):
        steps = build_guidance(self._left_turn_route(), EMPTY_SD_NAV)
        mid = steps[1]
        assert mid.maneuver_at_end == "left", (
            f"Expected 'left', got '{mid.maneuver_at_end}' (heading={mid.heading_change_deg:.1f}°)"
        )

    def test_left_turn_heading_close_to_minus_90(self):
        steps = build_guidance(self._left_turn_route(), EMPTY_SD_NAV)
        mid = steps[1]
        assert abs(mid.heading_change_deg - (-90.0)) < 2.0, (
            f"Expected ~-90°, got {mid.heading_change_deg:.2f}°"
        )

    def test_left_right_heading_sign_opposite(self):
        right_steps = build_guidance(self._right_turn_route(), EMPTY_SD_NAV)
        left_steps = build_guidance(self._left_turn_route(), EMPTY_SD_NAV)
        right_heading = right_steps[1].heading_change_deg
        left_heading = left_steps[1].heading_change_deg
        assert right_heading > 0, "Right turn should have positive heading change"
        assert left_heading < 0, "Left turn should have negative heading change"
        assert abs(right_heading + left_heading) < 2.0, "Should be symmetric"


class TestBoundaryValues:
    """Test the slight/sharp/u-turn degree thresholds."""

    def _route_with_angle(self, angle_deg: float) -> dict[str, Any]:
        """Route with one intermediate turn of exactly angle_deg degrees.

        Positive = right turn, negative = left turn.
        """
        # Edge 0 goes East.
        # Edge 1 turns by angle_deg (positive = right in navigation convention).
        angle_rad = math.radians(-angle_deg)  # negate for coordinate system
        x2 = 10.0 + 10.0 * math.cos(angle_rad)
        y2 = 0.0 + 10.0 * math.sin(angle_rad)
        return _make_route([
            _make_edge_feature("e0", [[0, 0], [10, 0]], length_m=10.0),
            _make_edge_feature("e1", [[10, 0], [x2, y2]], length_m=10.0),
            _make_edge_feature("e2", [[x2, y2], [x2 + 1, y2]], length_m=1.0),
        ])

    def test_slight_right_at_19deg(self):
        steps = build_guidance(self._route_with_angle(19.0), EMPTY_SD_NAV, slight_deg=20.0)
        assert steps[1].maneuver_at_end == "straight"

    def test_slight_right_at_21deg(self):
        steps = build_guidance(self._route_with_angle(21.0), EMPTY_SD_NAV, slight_deg=20.0)
        assert steps[1].maneuver_at_end in {"slight_right", "right"}

    def test_sharp_right_at_130deg(self):
        steps = build_guidance(self._route_with_angle(130.0), EMPTY_SD_NAV, sharp_deg=120.0)
        assert steps[1].maneuver_at_end == "sharp_right"

    def test_u_turn_at_170deg(self):
        steps = build_guidance(self._route_with_angle(170.0), EMPTY_SD_NAV, u_turn_deg=165.0)
        assert steps[1].maneuver_at_end == "u_turn"

    def test_slight_left_at_21deg(self):
        steps = build_guidance(self._route_with_angle(-21.0), EMPTY_SD_NAV, slight_deg=20.0)
        assert steps[1].maneuver_at_end in {"slight_left", "left"}

    def test_sharp_left_at_130deg(self):
        steps = build_guidance(self._route_with_angle(-130.0), EMPTY_SD_NAV, sharp_deg=120.0)
        assert steps[1].maneuver_at_end == "sharp_left"


class TestSdNavIntegration:
    """Verify sd_nav_edge_maneuvers is populated from sd_nav."""

    def test_sd_nav_maneuvers_populated(self):
        route = _make_route([
            _make_edge_feature("e0", [[0, 0], [10, 0]], length_m=10.0),
            _make_edge_feature("e1", [[10, 0], [20, 0]], length_m=10.0),
        ])
        sd_nav = {
            "edges": [
                {"edge_id": "e0", "allowed_maneuvers": ["straight", "right"]},
                {"edge_id": "e1", "allowed_maneuvers": ["straight"]},
            ]
        }
        steps = build_guidance(route, sd_nav)
        assert steps[0].sd_nav_edge_maneuvers == ["straight", "right"]
        assert steps[1].sd_nav_edge_maneuvers == ["straight"]

    def test_missing_sd_nav_edge_returns_empty(self):
        route = _make_route([
            _make_edge_feature("e0", [[0, 0], [10, 0]], length_m=10.0),
            _make_edge_feature("e1", [[10, 0], [20, 0]], length_m=10.0),
        ])
        steps = build_guidance(route, EMPTY_SD_NAV)
        assert steps[0].sd_nav_edge_maneuvers == []


class TestSchemaValidation:
    """Output validates against guidance.schema.json."""

    def test_schema_accepts_output(self):
        from roadgraph_builder.validation import validate_guidance_document
        route = _make_route([
            _make_edge_feature("e0", [[0, 0], [10, 0]], length_m=10.0),
            _make_edge_feature("e1", [[10, 0], [10, -10]], length_m=10.0),
            _make_edge_feature("e2", [[10, -10], [10, -20]], length_m=10.0),
        ])
        steps = build_guidance(route, EMPTY_SD_NAV)
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
