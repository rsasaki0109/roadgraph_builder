from __future__ import annotations

from pathlib import Path

import pytest

from roadgraph_builder.utils.geo import load_wgs84_origin_json

ROOT = Path(__file__).resolve().parent.parent


def test_load_wgs84_origin_json():
    lat, lon = load_wgs84_origin_json(ROOT / "examples" / "toy_map_origin.json")
    assert abs(lat - 52.52) < 1e-6
    assert abs(lon - 13.405) < 1e-6


def test_load_origin_rejects_missing_keys(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text('{"lat0": 1}', encoding="utf-8")
    with pytest.raises(KeyError):
        load_wgs84_origin_json(p)
