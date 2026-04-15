"""Local tangent-plane meters ↔ WGS84 (small areas; same convention as OSM fetch script)."""

from __future__ import annotations

import math


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
