"""Minimal reader for LAS (ASPRS LiDAR) public header fields.

Only parses the **Public Header Block** — the fixed-layout preamble — which is
enough to expose point count, bbox, scale/offset, version, and point format
without needing to decode the per-point records. Supports LAS 1.0 – 1.4.

LAZ (compressed) files are delegated to ``laspy[lazrs]`` when that optional
dependency is installed (``pip install roadgraph-builder[laz]``). Without
``laspy`` the LAZ code path raises ``ImportError`` with an actionable message
and the uncompressed LAS fast path is unaffected.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


LAS_SIGNATURE = b"LASF"
# Point data formats 0–3 share the same 20-byte core (X, Y, Z, intensity,
# flags, classification, scan_angle_rank, user_data, point_source_id). Formats
# 1–5 append GPS time / color channels; we only need X/Y so reading the first
# 12 bytes per record is enough regardless of the record length on disk.
_SUPPORTED_POINT_FORMATS = frozenset({0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10})

# Offsets into the public header block (LAS 1.0–1.4 share this preamble).
_OFFSETS = {
    "version": (24, 2),  # u8 major, u8 minor
    "header_size": (94, "<H"),
    "offset_to_point_data": (96, "<I"),
    "point_data_format": (104, "<B"),
    "point_data_record_length": (105, "<H"),
    "legacy_point_count": (107, "<I"),
    "scale": (131, "<ddd"),
    "offset": (155, "<ddd"),
    # min/max on disk are stored as x_max, x_min, y_max, y_min, z_max, z_min.
    "minmax": (179, "<dddddd"),
}

# LAS 1.4 also stores a 64-bit point count at offset 247 inside the 375-byte
# header. Older versions do not use that field.
_LAS14_POINT_COUNT_OFFSET = 247


@dataclass(frozen=True)
class LASHeader:
    """Structured view of the LAS public header."""

    path: Path
    version: tuple[int, int]
    point_data_format: int
    point_data_record_length: int
    header_size: int
    offset_to_point_data: int
    point_count: int
    scale: tuple[float, float, float]
    offset: tuple[float, float, float]
    bbox: dict[str, float]

    def to_summary(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "version": f"{self.version[0]}.{self.version[1]}",
            "point_data_format": self.point_data_format,
            "point_data_record_length_bytes": self.point_data_record_length,
            "header_size_bytes": self.header_size,
            "offset_to_point_data_bytes": self.offset_to_point_data,
            "point_count": self.point_count,
            "scale": {"x": self.scale[0], "y": self.scale[1], "z": self.scale[2]},
            "offset": {"x": self.offset[0], "y": self.offset[1], "z": self.offset[2]},
            "bbox": self.bbox,
        }


def read_las_header(path: str | Path) -> LASHeader:
    """Parse the public header of a LAS file; raise ``ValueError`` on bad input."""
    p = Path(path)
    with p.open("rb") as fh:
        # LAS 1.4 headers are 375 bytes; older ones are smaller. 512 is safe.
        data = fh.read(512)

    if len(data) < 227:
        raise ValueError(f"LAS file too short to contain a public header: {p}")
    if data[:4] != LAS_SIGNATURE:
        raise ValueError(f"Not a LAS file (missing 'LASF' signature): {p}")

    offset, _ = _OFFSETS["version"]
    version = (data[offset], data[offset + 1])

    header_size = struct.unpack_from(_OFFSETS["header_size"][1], data, _OFFSETS["header_size"][0])[0]
    offset_to_point_data = struct.unpack_from(
        _OFFSETS["offset_to_point_data"][1], data, _OFFSETS["offset_to_point_data"][0]
    )[0]
    point_data_format = struct.unpack_from(
        _OFFSETS["point_data_format"][1], data, _OFFSETS["point_data_format"][0]
    )[0]
    point_data_record_length = struct.unpack_from(
        _OFFSETS["point_data_record_length"][1], data, _OFFSETS["point_data_record_length"][0]
    )[0]
    legacy_point_count = struct.unpack_from(
        _OFFSETS["legacy_point_count"][1], data, _OFFSETS["legacy_point_count"][0]
    )[0]

    scale = struct.unpack_from(_OFFSETS["scale"][1], data, _OFFSETS["scale"][0])
    offset_xyz = struct.unpack_from(_OFFSETS["offset"][1], data, _OFFSETS["offset"][0])
    max_x, min_x, max_y, min_y, max_z, min_z = struct.unpack_from(
        _OFFSETS["minmax"][1], data, _OFFSETS["minmax"][0]
    )

    point_count = legacy_point_count
    if version >= (1, 4) and header_size >= _LAS14_POINT_COUNT_OFFSET + 8 and len(data) >= _LAS14_POINT_COUNT_OFFSET + 8:
        extended = struct.unpack_from("<Q", data, _LAS14_POINT_COUNT_OFFSET)[0]
        if extended:
            point_count = extended

    return LASHeader(
        path=p,
        version=version,
        point_data_format=point_data_format,
        point_data_record_length=point_data_record_length,
        header_size=header_size,
        offset_to_point_data=offset_to_point_data,
        point_count=point_count,
        scale=(float(scale[0]), float(scale[1]), float(scale[2])),
        offset=(float(offset_xyz[0]), float(offset_xyz[1]), float(offset_xyz[2])),
        bbox={
            "x_min": float(min_x),
            "x_max": float(max_x),
            "y_min": float(min_y),
            "y_max": float(max_y),
            "z_min": float(min_z),
            "z_max": float(max_z),
        },
    )


def _load_points_xy_from_laz(path: Path) -> np.ndarray:
    """LAZ path: delegate to ``laspy[lazrs]`` if the optional extra is installed."""
    try:
        import laspy  # type: ignore[import-not-found]
    except ImportError as e:  # pragma: no cover - tested via monkeypatch
        raise ImportError(
            "LAZ decoding requires the optional 'laz' extra. "
            "Install with: pip install 'roadgraph-builder[laz]'"
        ) from e
    reader = laspy.read(str(path))
    xy = np.empty((len(reader.x), 2), dtype=np.float64)
    xy[:, 0] = np.asarray(reader.x, dtype=np.float64)
    xy[:, 1] = np.asarray(reader.y, dtype=np.float64)
    return xy


def load_points_xy_from_las(path: str | Path) -> np.ndarray:
    """Return an ``(N, 2)`` float64 array of X/Y in meters from a LAS/LAZ file.

    Only the X/Y ints are read from each point record; scale and offset from
    the public header are applied (``x = x_int * scale_x + offset_x``). Point
    data formats 0–10 share a common 4-byte X / 4-byte Y / 4-byte Z prefix
    at the start of every record, so this works without distinguishing the
    format beyond the header-reported record length.

    ``.laz`` files are delegated to ``laspy[lazrs]`` when that optional extra
    is installed. Without it, calls on ``.laz`` raise ``ImportError`` with
    instructions; ``.las`` keeps working regardless.
    """
    p = Path(path)
    if p.suffix.lower() == ".laz":
        return _load_points_xy_from_laz(p)
    header = read_las_header(path)
    if header.point_data_format not in _SUPPORTED_POINT_FORMATS:
        raise ValueError(
            f"Unsupported LAS point data format {header.point_data_format} in {path}"
        )

    record_length = header.point_data_record_length
    if record_length < 12:
        raise ValueError(
            f"LAS point_data_record_length {record_length} in {path} is too small to hold X/Y/Z"
        )

    scale_x, scale_y, _ = header.scale
    offset_x, offset_y, _ = header.offset
    point_count = header.point_count

    p = Path(path)
    with p.open("rb") as fh:
        fh.seek(header.offset_to_point_data)
        blob = fh.read(record_length * point_count)
    if len(blob) < record_length * point_count:
        raise ValueError(
            f"LAS file {p} truncated: expected {record_length * point_count} point bytes, "
            f"got {len(blob)}"
        )

    # Slice the X/Y ints out of each record in one pass using numpy strides.
    buf = np.frombuffer(blob, dtype=np.uint8).reshape(point_count, record_length)
    xi = buf[:, 0:4].copy().view(np.int32).reshape(point_count)
    yi = buf[:, 4:8].copy().view(np.int32).reshape(point_count)

    xy = np.empty((point_count, 2), dtype=np.float64)
    xy[:, 0] = xi.astype(np.float64) * scale_x + offset_x
    xy[:, 1] = yi.astype(np.float64) * scale_y + offset_y
    return xy


__all__ = ["LASHeader", "load_points_xy_from_las", "read_las_header"]
