"""Local tangent-plane meters ↔ WGS84 (small areas; same convention as OSM fetch script)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, cast


def load_wgs84_origin_json(path: str | Path) -> tuple[float, float]:
    """Read ``lat0`` and ``lon0`` (degrees) from a JSON object (e.g. ``*_origin.json``)."""
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(f"Origin JSON must be an object: {p}")
    data = cast(dict[str, Any], raw)
    if "lat0" not in data or "lon0" not in data:
        raise KeyError(f"Origin JSON must contain lat0 and lon0: {p}")
    return float(data["lat0"]), float(data["lon0"])


def meters_to_lonlat(x_m: float, y_m: float, lat0_deg: float, lon0_deg: float) -> tuple[float, float]:
    """Inverse of local ENU from origin (lat0, lon0); returns (lon, lat) in degrees."""
    r = 6371000.0
    lat_r = math.radians(lat0_deg)
    lat_deg = lat0_deg + math.degrees(y_m / r)
    lon_deg = lon0_deg + math.degrees(x_m / (r * math.cos(lat_r)))
    return lon_deg, lat_deg


def lonlat_to_meters(lon_deg: float, lat_deg: float, lat0_deg: float, lon0_deg: float) -> tuple[float, float]:
    """Forward transform (matches scripts/fetch_osm_trackpoints._local_xy_m)."""
    r = 6371000.0
    lat_r = math.radians(lat0_deg)
    x = r * math.radians(lon_deg - lon0_deg) * math.cos(lat_r)
    y = r * math.radians(lat_deg - lat0_deg)
    return x, y
