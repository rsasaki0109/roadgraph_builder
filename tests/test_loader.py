from __future__ import annotations

import numpy as np

from roadgraph_builder.io.trajectory.loader import load_trajectory_csv


def test_load_trajectory_sorts_by_time(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("timestamp,x,y\n2,1,0\n0,0,0\n1,0.5,0\n", encoding="utf-8")
    t = load_trajectory_csv(p)
    np.testing.assert_array_almost_equal(t.timestamps, [0.0, 1.0, 2.0])
    assert t.xy.shape == (3, 2)
    assert t.timestamps.dtype == np.float64
    assert t.xy.dtype == np.float64


def test_load_trajectory_xy_dtype_float32_opt_in(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("timestamp,x,y\n0,0,0\n1,0.5,0\n", encoding="utf-8")

    t = load_trajectory_csv(p, xy_dtype=np.float32)

    assert t.timestamps.dtype == np.float64
    assert t.xy.dtype == np.float32


def test_load_trajectory_z_stays_float64_with_float32_xy(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("timestamp,x,y,z\n0,0,0,10\n1,1,0,11.5\n", encoding="utf-8")

    t = load_trajectory_csv(p, load_z=True, xy_dtype="float32")

    assert t.xy.dtype == np.float32
    assert t.z is not None
    assert t.z.dtype == np.float64


def test_load_trajectory_rejects_unsupported_xy_dtype(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("timestamp,x,y\n0,0,0\n1,1,0\n", encoding="utf-8")

    try:
        load_trajectory_csv(p, xy_dtype=np.float16)
    except ValueError as e:
        assert "float64 or float32" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_load_rejects_missing_column(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("a,b\n0,0\n", encoding="utf-8")
    try:
        load_trajectory_csv(p)
    except ValueError as e:
        assert "timestamp" in str(e).lower() or "Missing" in str(e)
    else:
        raise AssertionError("expected ValueError")
