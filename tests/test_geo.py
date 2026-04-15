from __future__ import annotations

import math

from roadgraph_builder.utils.geo import lonlat_to_meters, meters_to_lonlat


def test_meters_lonlat_roundtrip():
    lat0, lon0 = 52.5, 13.4
    lon_t, lat_t = 13.41, 52.51
    x, y = lonlat_to_meters(lon_t, lat_t, lat0, lon0)
    lon2, lat2 = meters_to_lonlat(x, y, lat0, lon0)
    assert abs(lon2 - lon_t) < 1e-5
    assert abs(lat2 - lat_t) < 1e-5


def test_meters_lonlat_near_origin():
    lat0, lon0 = 35.0, 139.0
    x, y = 12.0, -7.0
    lon, lat = meters_to_lonlat(x, y, lat0, lon0)
    assert math.isfinite(lon) and math.isfinite(lat)
