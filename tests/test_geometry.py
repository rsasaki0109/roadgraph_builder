from __future__ import annotations

import numpy as np

from roadgraph_builder.utils.geometry import (
    centerline_from_points,
    merge_endpoints_union_find,
    simplify_polyline_rdp,
    split_indices_by_step,
)


def test_split_by_gap():
    xy = np.array([[0, 0], [1, 0], [100, 0]], dtype=np.float64)
    ranges = split_indices_by_step(xy, max_step=25.0)
    assert ranges == [(0, 2), (2, 3)]


def test_merge_endpoints():
    pts = [(0.0, 0.0), (0.5, 0.0), (10.0, 0.0), (10.2, 0.0)]
    pos, idx = merge_endpoints_union_find(pts, merge_dist=1.0)
    assert idx[0] == idx[1]
    assert idx[2] == idx[3]
    assert len(pos) == 2


def test_simplify_polyline_rdp():
    pts = [(0.0, 0.0), (1.0, 5.0), (2.0, 0.0), (10.0, 0.0)]
    s = simplify_polyline_rdp(pts, epsilon=0.5)
    assert len(s) >= 2
    assert s[0] == pts[0] and s[-1] == pts[-1]


def test_centerline_nonempty():
    xy = np.array([[i, 0.1 * i] for i in range(20)], dtype=np.float64)
    pl = centerline_from_points(xy, num_bins=8)
    assert len(pl) >= 2
