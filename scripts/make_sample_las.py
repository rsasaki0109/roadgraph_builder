#!/usr/bin/env python3
"""Write a tiny, valid LAS 1.2 file (point data format 0) for demos.

The purpose is to have a real on-disk LAS artefact that ``inspect-lidar``
can read in CI and demos. It encodes N points arranged along two parallel
lanes (centre line + offsets) in the LAS integer coordinate space. The
header's bbox and point count are populated accordingly so
``read_las_header`` round-trips with meaningful numbers.

Usage (from repo root):

    python scripts/make_sample_las.py examples/sample_lidar.las
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


SCALE = (0.01, 0.01, 0.01)
OFFSET = (0.0, 0.0, 0.0)
HEADER_SIZE = 227
POINT_RECORD_LENGTH = 20  # LAS point format 0.


def _build_points(step_m: float = 2.0, length_m: float = 50.0, lane_width_m: float = 3.5) -> list[tuple[float, float, float]]:
    pts: list[tuple[float, float, float]] = []
    x = 0.0
    while x <= length_m:
        pts.append((x, -lane_width_m / 2.0, 0.10))
        pts.append((x, lane_width_m / 2.0, 0.12))
        x += step_m
    return pts


def _encode_point(xm: float, ym: float, zm: float) -> bytes:
    xi = int(round((xm - OFFSET[0]) / SCALE[0]))
    yi = int(round((ym - OFFSET[1]) / SCALE[1]))
    zi = int(round((zm - OFFSET[2]) / SCALE[2]))
    intensity = 0
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
        intensity,
        flags,
        classification,
        scan_angle_rank,
        user_data,
        point_source_id,
    )


def write_sample_las(path: Path) -> tuple[int, dict[str, float]]:
    points = _build_points()
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]

    offset_to_point_data = HEADER_SIZE
    header = bytearray(HEADER_SIZE)
    header[0:4] = b"LASF"
    header[24] = 1
    header[25] = 2
    struct.pack_into("<H", header, 94, HEADER_SIZE)
    struct.pack_into("<I", header, 96, offset_to_point_data)
    struct.pack_into("<B", header, 104, 0)  # point data format
    struct.pack_into("<H", header, 105, POINT_RECORD_LENGTH)
    struct.pack_into("<I", header, 107, len(points))
    struct.pack_into("<ddd", header, 131, *SCALE)
    struct.pack_into("<ddd", header, 155, *OFFSET)
    struct.pack_into(
        "<dddddd",
        header,
        179,
        max(xs),
        min(xs),
        max(ys),
        min(ys),
        max(zs),
        min(zs),
    )

    payload = b"".join(_encode_point(*p) for p in points)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + payload)
    return len(points), {
        "x_min": float(min(xs)),
        "x_max": float(max(xs)),
        "y_min": float(min(ys)),
        "y_max": float(max(ys)),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Write a tiny LAS 1.2 sample file for testing.")
    p.add_argument("output", type=Path)
    args = p.parse_args()
    count, bbox = write_sample_las(args.output)
    print(f"wrote {count} points to {args.output}")
    print(f"bbox x=[{bbox['x_min']},{bbox['x_max']}] y=[{bbox['y_min']},{bbox['y_max']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
