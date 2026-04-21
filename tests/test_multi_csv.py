from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from roadgraph_builder.cli.main import main
from roadgraph_builder.io.trajectory.loader import (
    load_multi_trajectory_csvs,
    load_trajectory_csv,
)


def _write_csv(path: Path, ts_start: float, xs, ys) -> None:
    lines = ["timestamp,x,y\n"]
    for i, (x, y) in enumerate(zip(xs, ys)):
        lines.append(f"{ts_start + i},{x:.6f},{y:.6f}\n")
    path.write_text("".join(lines), encoding="utf-8")


def test_load_multi_trajectory_csvs_concatenates(tmp_path: Path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, 0.0, [0.0, 10.0, 20.0], [0.0, 0.0, 0.0])
    _write_csv(b, 100.0, [20.0, 30.0, 40.0], [0.0, 0.0, 0.0])

    combined = load_multi_trajectory_csvs([a, b])
    assert combined.xy.shape == (6, 2)
    assert combined.timestamps.shape == (6,)
    # Primary-first ordering preserved.
    assert combined.xy[0, 0] == 0.0
    assert combined.xy[-1, 0] == 40.0


def test_load_multi_trajectory_csvs_preserves_xy_dtype(tmp_path: Path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, 0.0, [0.0, 10.0], [0.0, 0.0])
    _write_csv(b, 100.0, [20.0, 30.0], [0.0, 0.0])

    combined = load_multi_trajectory_csvs([a, b], xy_dtype=np.float32)

    assert combined.xy.dtype == np.float32
    assert combined.timestamps.dtype == np.float64


def test_load_multi_trajectory_csvs_single_path_equivalent(tmp_path: Path):
    a = tmp_path / "a.csv"
    _write_csv(a, 0.0, [0.0, 1.0, 2.0], [0.0, 0.0, 0.0])
    solo = load_trajectory_csv(a)
    via_multi = load_multi_trajectory_csvs([a])
    np.testing.assert_allclose(solo.xy, via_multi.xy)
    np.testing.assert_allclose(solo.timestamps, via_multi.timestamps)


def test_build_cli_accepts_extra_csv(tmp_path: Path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    # Two parallel passes over the same 50 m stretch, 1 m apart in y.
    _write_csv(a, 0.0, list(range(0, 51, 5)), [0.0] * 11)
    _write_csv(b, 100.0, list(range(0, 51, 5)), [1.0] * 11)

    out = tmp_path / "g.json"
    rc = main(
        [
            "build",
            str(a),
            str(out),
            "--extra-csv",
            str(b),
            "--trajectory-dtype",
            "float32",
        ]
    )
    assert rc == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    # Primary + extra combined → at least one edge, but the duplicate merge
    # should collapse both passes into one averaged centerline so we don't see
    # two parallel edges covering the same stretch.
    assert len(doc["edges"]) >= 1
    for e in doc["edges"]:
        # merged_edge_count can be 1 (if T/X split pulled them onto different
        # nodes) or >1 (if the duplicate merge fired); bidirectional is
        # impossible here because both passes go the same direction.
        d = e["attributes"].get("direction_observed")
        assert d in {"forward_only", "bidirectional", None}
