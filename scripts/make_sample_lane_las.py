#!/usr/bin/env python3
"""Write a synthetic LAS 1.2 file with intensity-encoded lane markings.

Generates a straight-line road segment with:
- Road surface points (intensity 50) uniformly distributed laterally.
- Left lane marking at +1.75 m offset (intensity 200).
- Right lane marking at -1.75 m offset (intensity 200).

This is the canonical fixture for test_lane_marking_synthetic.py.

Usage (from repo root):
    python scripts/make_sample_lane_las.py tests/fixtures/lane_markings_synth.las
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


SCALE = (0.001, 0.001, 0.001)
OFFSET = (0.0, 0.0, 0.0)
HEADER_SIZE = 227
POINT_RECORD_LENGTH = 20  # LAS point format 0.


def _encode_point(xm: float, ym: float, zm: float, intensity: int) -> bytes:
    xi = int(round((xm - OFFSET[0]) / SCALE[0]))
    yi = int(round((ym - OFFSET[1]) / SCALE[1]))
    zi = int(round((zm - OFFSET[2]) / SCALE[2]))
    # Clamp intensity to uint16 range.
    intensity_u16 = max(0, min(65535, intensity))
    flags = 0
    classification = 2  # ground
    scan_angle_rank = 0
    user_data = 0
    point_source_id = 0
    return struct.pack(
        "<iiiHBbBBH",
        xi,
        yi,
        zi,
        intensity_u16,
        flags,
        classification,
        scan_angle_rank,
        user_data,
        point_source_id,
    )


def build_lane_points(
    step_m: float = 1.0,
    length_m: float = 30.0,
    marking_offset_m: float = 1.75,
    surface_intensity: int = 50,
    marking_intensity: int = 200,
    surface_lateral_count: int = 6,
) -> list[tuple[float, float, float, int]]:
    """Build synthetic point list (x, y, z, intensity).

    Road surface: uniform lateral spread at low intensity.
    Lane markings: tight cluster at ±marking_offset_m at high intensity.
    """
    pts: list[tuple[float, float, float, int]] = []
    import numpy as _np
    rng = _np.random.default_rng(42)

    s = 0.0
    while s <= length_m:
        # Road surface — several points spread across ±2 m laterally.
        for t in _np.linspace(-2.0, 2.0, surface_lateral_count):
            pts.append((s, float(t), 0.0, surface_intensity))
        # Left lane marking cluster (3 close points).
        for dt in [-0.02, 0.0, 0.02]:
            pts.append((s, marking_offset_m + dt, 0.0, marking_intensity))
        # Right lane marking cluster (3 close points).
        for dt in [-0.02, 0.0, 0.02]:
            pts.append((s, -marking_offset_m + dt, 0.0, marking_intensity))
        s += step_m

    return pts


def write_lane_las(path: Path) -> tuple[int, float]:
    """Write synthetic lane marking LAS file. Returns (point_count, marking_offset_m)."""
    marking_offset_m = 1.75
    points = build_lane_points(marking_offset_m=marking_offset_m)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]

    header = bytearray(HEADER_SIZE)
    header[0:4] = b"LASF"
    header[24] = 1
    header[25] = 2
    struct.pack_into("<H", header, 94, HEADER_SIZE)
    struct.pack_into("<I", header, 96, HEADER_SIZE)
    struct.pack_into("<B", header, 104, 0)  # point data format 0
    struct.pack_into("<H", header, 105, POINT_RECORD_LENGTH)
    struct.pack_into("<I", header, 107, len(points))
    struct.pack_into("<ddd", header, 131, *SCALE)
    struct.pack_into("<ddd", header, 155, *OFFSET)
    struct.pack_into(
        "<dddddd",
        header,
        179,
        max(xs), min(xs),
        max(ys), min(ys),
        max(zs), min(zs),
    )

    payload = b"".join(_encode_point(*p) for p in points)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + payload)
    return len(points), marking_offset_m


def main() -> int:
    p = argparse.ArgumentParser(description="Write synthetic lane-marking LAS for testing.")
    p.add_argument("output", type=Path, nargs="?", default=Path("tests/fixtures/lane_markings_synth.las"))
    args = p.parse_args()
    count, offset = write_lane_las(args.output)
    print(f"wrote {count} points to {args.output} (lane markings at ±{offset} m)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
