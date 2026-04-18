#!/usr/bin/env python3
"""Download OSM drivable highway ways inside a bbox via Overpass API.

Writes the raw Overpass JSON response (ways + referenced nodes). Use together
with ``roadgraph_builder build-osm-graph`` to produce a topologically honest
road graph where every OSM junction becomes a graph node — a prerequisite for
mapping OSM ``type=restriction`` relations onto graph turn_restrictions.

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
    "roadgraph_builder/0.4 (+https://github.com/rsasaki0109/roadgraph_builder)"
)
# Drivable road classes. Matches what we plan to map turn restrictions onto.
DEFAULT_HIGHWAY_CLASSES = (
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
    "service",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
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
  way["highway"~"^({regex})$"]
    ({min_lat},{min_lon},{max_lat},{max_lon});
);
out body;
>;
out skel qt;
""".strip()


def fetch_overpass(
    bbox: str,
    *,
    user_agent: str,
    endpoint: str = OVERPASS_URL,
    classes: tuple[str, ...] = DEFAULT_HIGHWAY_CLASSES,
) -> dict[str, object]:
    query = _build_query(bbox, classes)
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = resp.read()
    return json.loads(payload.decode("utf-8"))


def _summarize(data: dict[str, object]) -> dict[str, int]:
    counts = {"way": 0, "node": 0}
    elements = data.get("elements", [])
    if isinstance(elements, list):
        for el in elements:
            if isinstance(el, dict):
                kind = el.get("type")
                if isinstance(kind, str) and kind in counts:
                    counts[kind] += 1
    return counts


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch OSM highway ways (raw Overpass JSON).")
    p.add_argument("-o", "--output", type=Path, required=True, help="Output JSON path.")
    p.add_argument("--bbox", required=True, help="min_lon,min_lat,max_lon,max_lat.")
    p.add_argument(
        "--user-agent",
        default=os.environ.get("ROADGRAPH_USER_AGENT", DEFAULT_USER_AGENT),
        help="HTTP User-Agent (OSMF policy).",
    )
    p.add_argument(
        "--endpoint",
        default=os.environ.get("OVERPASS_ENDPOINT", OVERPASS_URL),
        help="Overpass instance URL. Mirrors: kumi.systems, private.coffee.",
    )
    p.add_argument(
        "--classes",
        default=",".join(DEFAULT_HIGHWAY_CLASSES),
        help="Comma-separated highway values to include.",
    )
    args = p.parse_args()

    classes = tuple(c.strip() for c in args.classes.split(",") if c.strip())
    try:
        data = fetch_overpass(
            args.bbox, user_agent=args.user_agent, endpoint=args.endpoint, classes=classes
        )
    except urllib.error.HTTPError as e:
        print(f"HTTP error: {e}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"Network error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Bad argument: {e}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    counts = _summarize(data)
    print(f"Wrote {args.output}: {counts['way']} ways, {counts['node']} nodes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
