"""Load sparse LiDAR / survey points in local meters (same frame as trajectory)."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def load_points_xy_csv(path: str | Path) -> np.ndarray:
    """Load an ``(N, 2)`` float64 array from a text file: two columns **x y** per row.

    - Comma- or whitespace-separated.
    - Lines starting with ``#`` and empty lines are skipped.
    - The first row is treated as a header if its first two tokens are not both numeric.

    Raises:
        ValueError: No numeric rows found.
    """
    path = Path(path)
    rows: list[tuple[float, float]] = []
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.replace(",", " ").split()
            if len(parts) < 2:
                continue
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                if i == 0:
                    continue
                raise
            rows.append((x, y))
    if not rows:
        raise ValueError(f"No numeric x,y rows in {path}")
    return np.asarray(rows, dtype=np.float64)
