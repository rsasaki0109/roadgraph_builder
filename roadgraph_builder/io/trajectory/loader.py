"""Trajectory CSV loading (geometry path; semantics are separate in the future)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Trajectory:
    """Trajectory as ordered samples in 2D (or optionally 3D).

    ``xy`` always holds the (n, 2) XY plane; ``z`` is an optional (n,) array
    of elevation values present only when the source CSV had a ``z`` column
    and the caller requested 3D loading.
    """

    timestamps: np.ndarray  # shape (n,)
    xy: np.ndarray  # shape (n, 2)
    z: np.ndarray | None = None  # shape (n,) or None for 2D-only

    def __len__(self) -> int:
        return int(self.xy.shape[0])


def load_trajectory_csv(path: str | Path, *, load_z: bool = False) -> Trajectory:
    """Load CSV with columns timestamp, x, y (and optional z when load_z=True).

    When ``load_z=True`` and the CSV has a ``z`` column, the returned
    :class:`Trajectory` carries a non-None ``z`` array.  When ``load_z=False``
    (the default) or the column is absent, ``z`` is ``None`` and output is
    byte-identical to pre-3D1 behaviour.
    """
    path = Path(path)
    rows_ts: list[float] = []
    rows_xy: list[tuple[float, float]] = []
    rows_z: list[float] = []

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"Empty or invalid CSV: {path}")

        fields_lower = {name.lower(): name for name in reader.fieldnames}
        for req in ("timestamp", "x", "y"):
            if req not in fields_lower:
                raise ValueError(
                    f"Missing required column '{req}' in {path}; found {reader.fieldnames}"
                )

        t_col = fields_lower["timestamp"]
        x_col = fields_lower["x"]
        y_col = fields_lower["y"]
        z_col = fields_lower.get("z")
        has_z = load_z and z_col is not None

        for row in reader:
            rows_ts.append(float(row[t_col]))
            rows_xy.append((float(row[x_col]), float(row[y_col])))
            if has_z:
                rows_z.append(float(row[z_col]))  # type: ignore[index]

    if not rows_ts:
        raise ValueError(f"No data rows in {path}")

    timestamps = np.asarray(rows_ts, dtype=np.float64)
    xy = np.asarray(rows_xy, dtype=np.float64)
    order = np.argsort(timestamps)

    z_arr: np.ndarray | None = None
    if has_z:
        z_arr = np.asarray(rows_z, dtype=np.float64)[order]

    return Trajectory(timestamps=timestamps[order], xy=xy[order], z=z_arr)


def load_multi_trajectory_csvs(paths, *, load_z: bool = False) -> Trajectory:
    """Concatenate several trajectory CSVs assumed to share the same meter origin.

    Takes an iterable of file paths (primary first); returns a single
    :class:`Trajectory` whose samples are **not** re-sorted across files (each
    file's internal timestamp order is preserved, but the concatenation order
    reflects the argument order). Gap-based segmentation downstream still
    treats spatial jumps between files as new segments, so two non-overlapping
    passes will naturally become separate polylines while overlapping traces
    get fused by the existing duplicate / near-parallel merge passes.

    When ``load_z=True``, elevation data is concatenated when available.
    """
    trajectories = [load_trajectory_csv(p, load_z=load_z) for p in paths]
    if not trajectories:
        raise ValueError("load_multi_trajectory_csvs requires at least one path")
    if len(trajectories) == 1:
        return trajectories[0]
    timestamps = np.concatenate([t.timestamps for t in trajectories])
    xy = np.concatenate([t.xy for t in trajectories], axis=0)
    # Merge z arrays: only set if all have z data
    has_z_all = all(t.z is not None for t in trajectories)
    z_arr: np.ndarray | None = None
    if has_z_all:
        z_arr = np.concatenate([t.z for t in trajectories])  # type: ignore[misc]
    return Trajectory(timestamps=timestamps, xy=xy, z=z_arr)
