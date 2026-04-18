"""Trajectory CSV loading (geometry path; semantics are separate in the future)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Trajectory:
    """Trajectory as ordered samples in 2D."""

    timestamps: np.ndarray  # shape (n,)
    xy: np.ndarray  # shape (n, 2)

    def __len__(self) -> int:
        return int(self.xy.shape[0])


def load_trajectory_csv(path: str | Path) -> Trajectory:
    """Load CSV with columns timestamp, x, y (additional columns ignored)."""
    path = Path(path)
    rows_ts: list[float] = []
    rows_xy: list[tuple[float, float]] = []

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

        for row in reader:
            rows_ts.append(float(row[t_col]))
            rows_xy.append((float(row[x_col]), float(row[y_col])))

    if not rows_ts:
        raise ValueError(f"No data rows in {path}")

    timestamps = np.asarray(rows_ts, dtype=np.float64)
    xy = np.asarray(rows_xy, dtype=np.float64)
    order = np.argsort(timestamps)
    return Trajectory(timestamps=timestamps[order], xy=xy[order])


def load_multi_trajectory_csvs(paths) -> Trajectory:
    """Concatenate several trajectory CSVs assumed to share the same meter origin.

    Takes an iterable of file paths (primary first); returns a single
    :class:`Trajectory` whose samples are **not** re-sorted across files (each
    file's internal timestamp order is preserved, but the concatenation order
    reflects the argument order). Gap-based segmentation downstream still
    treats spatial jumps between files as new segments, so two non-overlapping
    passes will naturally become separate polylines while overlapping traces
    get fused by the existing duplicate / near-parallel merge passes.
    """
    trajectories = [load_trajectory_csv(p) for p in paths]
    if not trajectories:
        raise ValueError("load_multi_trajectory_csvs requires at least one path")
    if len(trajectories) == 1:
        return trajectories[0]
    timestamps = np.concatenate([t.timestamps for t in trajectories])
    xy = np.concatenate([t.xy for t in trajectories], axis=0)
    return Trajectory(timestamps=timestamps, xy=xy)
