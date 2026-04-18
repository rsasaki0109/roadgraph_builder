from __future__ import annotations

import math

from roadgraph_builder.hd.boundaries import centerline_lane_boundaries


def _signed_dist_to_line(pt, a, b):
    """Signed perpendicular distance from pt to the infinite line through a→b.

    Positive when pt sits to the left of the a→b direction (so the returned
    value for a correctly-offset left ribbon stays equal to the offset).
    """
    abx, aby = b[0] - a[0], b[1] - a[1]
    l = math.hypot(abx, aby)
    apx, apy = pt[0] - a[0], pt[1] - a[1]
    return (abx * apy - aby * apx) / l


def test_straight_centerline_gives_exact_offset():
    cl = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0)]
    left, right = centerline_lane_boundaries(cl, lane_width_m=3.5)
    assert len(left) == 4 and len(right) == 4
    for p in left:
        assert math.isclose(p[1], 1.75, abs_tol=1e-9)
    for p in right:
        assert math.isclose(p[1], -1.75, abs_tol=1e-9)


def test_right_angle_bend_keeps_uniform_perpendicular_distance():
    # 90° left turn: centerline runs along +x then +y.
    cl = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    half = 1.0
    left, right = centerline_lane_boundaries(cl, lane_width_m=2.0 * half)
    a, b, c = cl[0], cl[1], cl[2]

    corner_left = left[1]
    corner_right = right[1]
    # Miter join places the corner on the bisector such that the perpendicular
    # distance to *each* incident edge's infinite line equals +half_width on
    # the left ribbon and -half_width on the right ribbon.
    assert math.isclose(_signed_dist_to_line(corner_left, a, b), half, abs_tol=1e-9)
    assert math.isclose(_signed_dist_to_line(corner_left, b, c), half, abs_tol=1e-9)
    assert math.isclose(_signed_dist_to_line(corner_right, a, b), -half, abs_tol=1e-9)
    assert math.isclose(_signed_dist_to_line(corner_right, b, c), -half, abs_tol=1e-9)


def test_acute_turn_falls_back_to_bevel():
    # Near 180° hair-pin — miter explodes, bevel should emit two offset points
    # at the corner vertex.
    cl = [(0.0, 0.0), (10.0, 0.0), (0.0, 0.1)]
    left, right = centerline_lane_boundaries(cl, lane_width_m=1.0, miter_limit=4.0)
    assert len(left) > len(cl), "expected bevel to add extra vertex"
    assert len(right) > len(cl)


def test_disabled_for_zero_width():
    left, right = centerline_lane_boundaries([(0.0, 0.0), (10.0, 0.0)], lane_width_m=0.0)
    assert left == [] and right == []


def test_ribbon_preserves_travel_direction_left_positive_y():
    cl = [(0.0, 0.0), (1.0, 0.0)]
    left, right = centerline_lane_boundaries(cl, lane_width_m=2.0)
    # Left of east-heading centerline is positive y.
    assert left[0][1] > 0.0
    assert right[0][1] < 0.0
