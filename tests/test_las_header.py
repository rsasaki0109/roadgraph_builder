from __future__ import annotations

import struct
from pathlib import Path

import pytest

from roadgraph_builder.io.lidar.las import read_las_header


def _synth_header(
    *,
    version: tuple[int, int] = (1, 2),
    point_data_format: int = 0,
    point_data_record_length: int = 20,
    legacy_point_count: int = 1234,
    scale: tuple[float, float, float] = (0.01, 0.01, 0.01),
    offset: tuple[float, float, float] = (100.0, 200.0, 300.0),
    bbox: tuple[float, float, float, float, float, float] = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
    extended_point_count: int | None = None,
) -> bytes:
    """Build a minimal but valid LAS public header block (227 or 375 bytes)."""
    x_min, x_max, y_min, y_max, z_min, z_max = bbox
    is_1_4 = version >= (1, 4)
    header_size = 375 if is_1_4 else 227
    buf = bytearray(header_size)
    buf[0:4] = b"LASF"
    buf[24] = version[0]
    buf[25] = version[1]
    struct.pack_into("<H", buf, 94, header_size)
    struct.pack_into("<I", buf, 96, header_size)  # offset_to_point_data
    struct.pack_into("<B", buf, 104, point_data_format)
    struct.pack_into("<H", buf, 105, point_data_record_length)
    struct.pack_into("<I", buf, 107, legacy_point_count)
    struct.pack_into("<ddd", buf, 131, *scale)
    struct.pack_into("<ddd", buf, 155, *offset)
    struct.pack_into("<dddddd", buf, 179, x_max, x_min, y_max, y_min, z_max, z_min)
    if is_1_4 and extended_point_count is not None:
        struct.pack_into("<Q", buf, 247, extended_point_count)
    return bytes(buf)


def test_read_las_header_1_2(tmp_path: Path):
    p = tmp_path / "tiny.las"
    p.write_bytes(_synth_header(legacy_point_count=500))
    h = read_las_header(p)
    assert h.version == (1, 2)
    assert h.point_count == 500
    assert h.point_data_format == 0
    assert h.scale == (0.01, 0.01, 0.01)
    assert h.offset == (100.0, 200.0, 300.0)
    assert h.bbox["x_min"] == 1.0
    assert h.bbox["x_max"] == 2.0
    assert h.bbox["y_min"] == 3.0
    assert h.bbox["y_max"] == 4.0
    summary = h.to_summary()
    assert summary["version"] == "1.2"
    assert summary["point_count"] == 500


def test_read_las_header_1_4_uses_extended_point_count(tmp_path: Path):
    p = tmp_path / "big.las"
    p.write_bytes(
        _synth_header(
            version=(1, 4),
            legacy_point_count=0,
            extended_point_count=5_000_000_000,  # > UINT32_MAX
        )
    )
    h = read_las_header(p)
    assert h.version == (1, 4)
    assert h.point_count == 5_000_000_000


def test_read_las_header_rejects_non_las(tmp_path: Path):
    p = tmp_path / "not_las.bin"
    p.write_bytes(b"NOPE" + b"\x00" * 300)
    with pytest.raises(ValueError, match="LASF"):
        read_las_header(p)


def test_read_las_header_rejects_short_file(tmp_path: Path):
    p = tmp_path / "stub.las"
    p.write_bytes(b"LASF" + b"\x00" * 10)
    with pytest.raises(ValueError, match="too short"):
        read_las_header(p)


def test_cli_inspect_lidar_prints_summary(tmp_path: Path, capsys):
    import json

    from roadgraph_builder.cli.main import main

    p = tmp_path / "cli.las"
    p.write_bytes(_synth_header(legacy_point_count=7, point_data_format=2))
    assert main(["inspect-lidar", str(p)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["point_count"] == 7
    assert summary["point_data_format"] == 2
    assert summary["version"] == "1.2"


def test_cli_inspect_lidar_missing_file(tmp_path: Path, capsys):
    from roadgraph_builder.cli.main import main

    missing = tmp_path / "nope.las"
    assert main(["inspect-lidar", str(missing)]) == 1
    err = capsys.readouterr().err
    assert "File not found" in err
