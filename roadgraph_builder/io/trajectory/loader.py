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
