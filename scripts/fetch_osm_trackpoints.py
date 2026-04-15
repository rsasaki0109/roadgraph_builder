#!/usr/bin/env python3
"""Download public GPS trackpoints from OpenStreetMap (ODbL) and write trajectory CSV.

API: GET https://api.openstreetmap.org/api/0.6/trackpoints?bbox=...
See: https://wiki.openstreetmap.org/wiki/API_v0.6#GPS_traces

Use a descriptive User-Agent (OSMF policy). Bounding box max size: 0.25° per side.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


OSM_TRACKPOINTS = "https://api.openstreetmap.org/api/0.6/trackpoints"
# Default: small area in Berlin (often has public traces); override with --bbox
DEFAULT_BBOX = "13.40,52.51,13.42,52.52"
# OSMF requires a descriptive User-Agent. Override for forks:
#   export ROADGRAPH_USER_AGENT='myapp/1.0 (+https://github.com/you/repo)'
DEFAULT_USER_AGENT = (
    "roadgraph_builder/0.2 (+https://github.com/rsasaki0109/roadgraph_builder)"
)


def _local_xy_m(lat_deg: float, lon_deg: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Approximate local ENU meters (good for small bboxes)."""
    r = 6371000.0
    lat_r = math.radians(lat0)
    x = r * math.radians(lon_deg - lon0) * math.cos(lat_r)
    y = r * math.radians(lat_deg - lat0)
    return x, y


def _parse_time(text: str | None) -> float:
    if not text:
        return 0.0
    t = text.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return 0.0


def fetch_gpx(bbox: str, page: int = 0, *, user_agent: str = DEFAULT_USER_AGENT) -> bytes:
    url = f"{OSM_TRACKPOINTS}?bbox={bbox}&page={page}"
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def gpx_to_points(
    gpx_bytes: bytes,
    max_points: int,
) -> tuple[
    list[tuple[float, float, float]],
    tuple[float, float],
    list[tuple[float, float, float]],
]:
    """Return (timestamp,x,y) meters, (lat0,lon0) origin, (timestamp,lon,lat) WGS84 rows."""
    root = ET.fromstring(gpx_bytes)
    ns = {"gpx": "http://www.topografix.com/GPX/1/0"}
    # GPX 1.0 from OSM; try with/without namespace
    trkpts = root.findall(".//gpx:trkpt", ns)
    if not trkpts:
        trkpts = root.findall(".//{http://www.topografix.com/GPX/1/0}trkpt")
    if not trkpts:
        trkpts = root.findall(".//trkpt")

    raw: list[tuple[float, float, float, float]] = []
    for el in trkpts:
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            continue
        la = float(lat)
        lo = float(lon)
        tim_el = el.find("gpx:time", ns) if ns else None
        if tim_el is None:
            tim_el = el.find("time")
        ts = _parse_time(tim_el.text if tim_el is not None else None)
        raw.append((ts, la, lo, ts))

    if not raw:
        return [], (0.0, 0.0), []

    raw.sort(key=lambda t: (t[0], t[3]))
    lat0 = raw[0][1]
    lon0 = raw[0][2]
    out: list[tuple[float, float, float]] = []
    wgs84: list[tuple[float, float, float]] = []
    seen = 0
    for ts, la, lo, _ in raw:
        if seen >= max_points:
            break
        x, y = _local_xy_m(la, lo, lat0, lon0)
        t_use = ts if ts > 0 else float(seen)
        out.append((t_use, x, y))
        wgs84.append((t_use, lo, la))
        seen += 1
    return out, (lat0, lon0), wgs84


def write_csv(path: Path, points: list[tuple[float, float, float]]) -> None:
    lines = ["timestamp,x,y\n"]
    for ts, x, y in points:
        lines.append(f"{ts:.3f},{x:.6f},{y:.6f}\n")
    path.write_text("".join(lines), encoding="utf-8")


def write_wgs84_csv(path: Path, rows: list[tuple[float, float, float]]) -> None:
    lines = ["timestamp,lon,lat\n"]
    for ts, lon, lat in rows:
        lines.append(f"{ts:.3f},{lon:.8f},{lat:.8f}\n")
    path.write_text("".join(lines), encoding="utf-8")


def write_origin_json(path: Path, lat0: float, lon0: float) -> None:
    path.write_text(
        json.dumps({"lat0": lat0, "lon0": lon0, "note": "WGS84 origin of local meters CSV (first point)"}, indent=2)
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch OSM public GPS traces -> trajectory CSV (x,y in local meters).")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("examples/osm_public_trackpoints.csv"),
        help="Output CSV path",
    )
    p.add_argument(
        "--bbox",
        default=DEFAULT_BBOX,
        help="min_lon,min_lat,max_lon,max_lat (max 0.25° span)",
    )
    p.add_argument("--max-points", type=int, default=1200, help="Cap points written")
    p.add_argument("--page", type=int, default=0, help="API page index")
    p.add_argument(
        "--user-agent",
        default=os.environ.get("ROADGRAPH_USER_AGENT", DEFAULT_USER_AGENT),
        help="HTTP User-Agent (OSMF policy). Env: ROADGRAPH_USER_AGENT.",
    )
    args = p.parse_args()

    try:
        gpx = fetch_gpx(args.bbox, page=args.page, user_agent=args.user_agent)
    except urllib.error.HTTPError as e:
        print(f"HTTP error: {e}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"Network error: {e}", file=sys.stderr)
        return 1

    pts, origin, wgs84 = gpx_to_points(gpx, args.max_points)
    if len(pts) < 2:
        print(
            "No trackpoints in response. Try another --bbox (area with public GPS uploads) or --page 1.",
            file=sys.stderr,
        )
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.output, pts)
    lat0, lon0 = origin
    origin_path = args.output.parent / f"{args.output.stem}_origin.json"
    wgs84_path = args.output.parent / f"{args.output.stem}_wgs84.csv"
    write_origin_json(origin_path, lat0, lon0)
    write_wgs84_csv(wgs84_path, wgs84)
    print(f"Wrote {len(pts)} points to {args.output}")
    print(f"Wrote origin {origin_path} and WGS84 {wgs84_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
