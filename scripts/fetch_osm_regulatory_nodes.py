#!/usr/bin/env python3
"""Download OSM regulatory nodes (traffic signals, stop, crossing, ...) inside
a bbox via the Overpass API.

Writes the raw Overpass JSON response with standalone nodes tagged
``highway=traffic_signals | stop | crossing | speed_camera``. Downstream,
``scripts/refresh_docs_assets.py`` projects those lon/lat fixes onto the
nearest graph edge so the committed Lanelet2 OSM ships *real* regulatory
markers instead of hand-authored synthetic samples.

Docs: https://wiki.openstreetmap.org/wiki/Key:highway
© OpenStreetMap contributors, ODbL 1.0. Keep raw output out of the repo.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_USER_AGENT = (
    "roadgraph_builder/0.7 (+https://github.com/rsasaki0109/roadgraph_builder)"
)
DEFAULT_HIGHWAY_REGULATORY = (
    "traffic_signals",
    "stop",
    "crossing",
    "speed_camera",
    "give_way",
)


def _build_query(bbox: str, classes: tuple[str, ...]) -> str:
    parts = bbox.split(",")
    if len(parts) != 4:
        raise ValueError(
            f"--bbox must be 'min_lon,min_lat,max_lon,max_lat', got {bbox!r}"
        )
    min_lon, min_lat, max_lon, max_lat = (p.strip() for p in parts)
    regex = "|".join(classes)
    return f"""
[out:json][timeout:90];
(
  node["highway"~"^({regex})$"]
    ({min_lat},{min_lon},{max_lat},{max_lon});
);
out body;
""".strip()


def fetch_overpass(
    bbox: str,
    *,
    user_agent: str,
    endpoint: str = OVERPASS_URL,
    classes: tuple[str, ...] = DEFAULT_HIGHWAY_REGULATORY,
) -> dict[str, object]:
    query = _build_query(bbox, classes)
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"User-Agent": user_agent, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = resp.read()
    return json.loads(payload.decode("utf-8"))


def _summarize(data: dict[str, object]) -> dict[str, int]:
    kinds: dict[str, int] = {}
    elements = data.get("elements", [])
    if isinstance(elements, list):
        for el in elements:
            if not isinstance(el, dict):
                continue
            if el.get("type") != "node":
                continue
            tags = el.get("tags") or {}
            if not isinstance(tags, dict):
                continue
            key = tags.get("highway", "?")
            kinds[key] = kinds.get(key, 0) + 1
    return kinds


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--bbox", required=True, help="min_lon,min_lat,max_lon,max_lat")
    p.add_argument(
        "--user-agent",
        default=os.environ.get("ROADGRAPH_USER_AGENT", DEFAULT_USER_AGENT),
    )
    p.add_argument(
        "--endpoint",
        default=os.environ.get("OVERPASS_ENDPOINT", OVERPASS_URL),
    )
    p.add_argument(
        "--classes",
        default=",".join(DEFAULT_HIGHWAY_REGULATORY),
        help="Comma-separated highway values to include (regulatory nodes).",
    )
    args = p.parse_args()

    classes = tuple(c.strip() for c in args.classes.split(",") if c.strip())
    try:
        data = fetch_overpass(
            args.bbox,
            user_agent=args.user_agent,
            endpoint=args.endpoint,
            classes=classes,
        )
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = _summarize(data)
    print(
        f"Wrote {args.output} with nodes by highway tag: {summary}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
