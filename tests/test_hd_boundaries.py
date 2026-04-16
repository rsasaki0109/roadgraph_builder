from __future__ import annotations

from roadgraph_builder.hd.boundaries import centerline_lane_boundaries


def test_straight_horizontal_offsets():
    pl = [(0.0, 0.0), (10.0, 0.0)]
    left, right = centerline_lane_boundaries(pl, 3.5)
    assert len(left) == 2
    h = 3.5 / 2.0
    assert left[0] == (0.0, h)
    assert left[1] == (10.0, h)
    assert right[0] == (0.0, -h)
    assert right[1] == (10.0, -h)


def test_single_point_returns_empty():
    left, right = centerline_lane_boundaries([(0.0, 0.0)], 3.5)
    assert left == [] and right == []


def test_nonpositive_width_returns_empty():
    assert centerline_lane_boundaries([(0.0, 0.0), (1.0, 0.0)], 0.0) == ([], [])
