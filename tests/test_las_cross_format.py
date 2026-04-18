"""Cross-format LAS regression tests.

Uses ``laspy`` (the optional ``[laz]`` extra) to generate real LAS files in
every point data record format we claim to support, then reads them back
through our pure-Python ``read_las_header`` / ``load_points_xy_from_las`` and
checks both the header metadata and the decoded XY match byte-for-byte with
``laspy.read``. Skips if ``laspy`` isn't installed so CI without the extra
still passes.

The existing ``test_las_header.py`` builds synthetic LAS bytes by hand — it
catches offset / struct drift in isolation but cannot prove we handle real
point records written by an independent encoder. These tests close that gap.
"""

from __future__ import annotations

import numpy as np
import pytest

from roadgraph_builder.io.lidar.las import (
    load_points_xy_from_las,
    read_las_header,
)


laspy = pytest.importorskip("laspy")


# (LAS version, point data record format). Covers every PDRF our reader
# claims to support, with LAS 1.4 for formats 6+ (where the 64-bit
# extended point count in the header is used).
_MATRIX = [
    ((1, 2), 0),
    ((1, 2), 1),
    ((1, 2), 2),
    ((1, 2), 3),
    ((1, 3), 4),
    ((1, 3), 5),
    ((1, 4), 6),
    ((1, 4), 7),
    ((1, 4), 8),
    ((1, 4), 9),
    ((1, 4), 10),
]


def _write_las(path, version, pdrf, n_points=128, seed=0):
    """Write a LAS with ``n_points`` random XY/Z inside [-1000, 1000] m."""
    rng = np.random.default_rng(seed)
    xs = rng.uniform(-1000.0, 1000.0, n_points)
    ys = rng.uniform(-1000.0, 1000.0, n_points)
    zs = rng.uniform(0.0, 100.0, n_points)

    hdr = laspy.LasHeader(version=f"{version[0]}.{version[1]}", point_format=pdrf)
    hdr.scales = [0.001, 0.001, 0.001]
    hdr.offsets = [0.0, 0.0, 0.0]
    las = laspy.LasData(header=hdr)
    las.x = xs
    las.y = ys
    las.z = zs
    las.write(str(path))
    return xs, ys


@pytest.mark.parametrize("version,pdrf", _MATRIX)
def test_reader_matches_laspy_across_formats(tmp_path, version, pdrf):
    path = tmp_path / f"cross_{version[0]}{version[1]}_pdrf{pdrf}.las"
    xs_src, ys_src = _write_las(path, version, pdrf, n_points=64)

    hdr = read_las_header(path)
    assert hdr.version == version
    assert hdr.point_data_format == pdrf
    assert hdr.point_count == 64

    xy = load_points_xy_from_las(path)
    assert xy.shape == (64, 2)

    # Cross-check against laspy (authoritative decoder).
    ref = laspy.read(str(path))
    ref_xy = np.column_stack([np.asarray(ref.x, dtype=np.float64),
                              np.asarray(ref.y, dtype=np.float64)])
    assert np.allclose(xy, ref_xy, atol=1e-6, rtol=0), (
        f"XY mismatch for LAS {version[0]}.{version[1]} PDRF {pdrf}: "
        f"max dx={np.abs(xy[:,0]-ref_xy[:,0]).max():.3e} "
        f"max dy={np.abs(xy[:,1]-ref_xy[:,1]).max():.3e}"
    )


def test_reader_handles_1_4_extended_point_count(tmp_path):
    """LAS 1.4 PDRF 6+ writes the 64-bit point count at offset 247.

    laspy uses that field; our reader has to as well for big clouds.
    """
    path = tmp_path / "large_1_4_pdrf6.las"
    rng = np.random.default_rng(1)
    n = 70_000
    xs = rng.uniform(-500.0, 500.0, n)
    ys = rng.uniform(-500.0, 500.0, n)
    zs = rng.uniform(0.0, 50.0, n)
    hdr = laspy.LasHeader(version="1.4", point_format=6)
    hdr.scales = [0.001, 0.001, 0.001]
    hdr.offsets = [0.0, 0.0, 0.0]
    las = laspy.LasData(header=hdr)
    las.x, las.y, las.z = xs, ys, zs
    las.write(str(path))

    h = read_las_header(path)
    assert h.version == (1, 4)
    assert h.point_count == n

    xy = load_points_xy_from_las(path)
    ref = laspy.read(str(path))
    ref_xy = np.column_stack([np.asarray(ref.x), np.asarray(ref.y)])
    assert np.allclose(xy, ref_xy, atol=1e-6)
