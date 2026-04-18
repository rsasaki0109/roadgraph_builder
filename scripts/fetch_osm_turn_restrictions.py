#!/usr/bin/env python3
"""Download OSM turn restriction relations inside a bbox via Overpass API.

Writes the raw Overpass JSON response (relations + referenced ways + nodes).
The output is a derivative of OpenStreetMap data — © OpenStreetMap
contributors, ODbL 1.0. Keep raw output out of the repository; convert it to
our-graph ``turn_restrictions.json`` with ``roadgraph_builder convert-osm-
restrictions`` before committing derivatives.

Docs: https://wiki.openstreetmap.org/wiki/Overpass_API
Relation reference: https://wiki.openstreetmap.org/wiki/Relation:restriction
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
# Overpass mirrors (try alternatives if the default is overloaded):
#   https://overpass.kumi.systems/api/interpreter
#   https://overpass.private.coffee/api/interpreter
DEFAULT_USER_AGENT = (
    "roadgraph_builder/0.4 (+https://github.com/rsasaki0109/roadgraph_builder)"
)
OSM_RESTRICTION_TYPES = (
    "no_left_turn",
    "no_right_turn",
    "no_straight_on",
    "no_u_turn",
    "only_left_turn",
    "only_right_turn",
    "only_straight_on",
)


def _build_query(bbox: str) -> str:
    parts = bbox.split(",")
    if len(parts) != 4:
        raise ValueError(
            f"--bbox must be 'min_lon,min_lat,max_lon,max_lat', got {bbox!r}"
        )
    min_lon, min_lat, max_lon, max_lat = (p.strip() for p in parts)
    regex = "|".join(OSM_RESTRICTION_TYPES)
    return f"""
[out:json][timeout:60];
(
  relation["type"="restriction"]["restriction"~"^({regex})$"]
    ({min_lat},{min_lon},{max_lat},{max_lon});
);
out body;
>;
out skel qt;
""".strip()


def fetch_overpass(
    bbox: str, *, user_agent: str, endpoint: str = OVERPASS_URL
) -> dict[str, object]:
    query = _build_query(bbox)
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = resp.read()
    return json.loads(payload.decode("utf-8"))


def _summarize(data: dict[str, object]) -> dict[str, int]:
    elements = data.get("elements", [])
    counts = {"relation": 0, "way": 0, "node": 0}
    if isinstance(elements, list):
        for el in elements:
            if isinstance(el, dict):
                kind = el.get("type")
                if isinstance(kind, str) and kind in counts:
                    counts[kind] += 1
    return counts


def main() -> int:
    p = argparse.ArgumentParser(
        description="Fetch OSM turn restriction relations (raw Overpass JSON)."
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Output JSON path (raw Overpass response, keep out of repo).",
    )
    p.add_argument(
        "--bbox",
        required=True,
        help="min_lon,min_lat,max_lon,max_lat (WGS84).",
    )
    p.add_argument(
        "--user-agent",
        default=os.environ.get("ROADGRAPH_USER_AGENT", DEFAULT_USER_AGENT),
        help="HTTP User-Agent (OSMF policy). Env: ROADGRAPH_USER_AGENT.",
    )
    p.add_argument(
        "--endpoint",
        default=os.environ.get("OVERPASS_ENDPOINT", OVERPASS_URL),
        help=(
            "Overpass instance URL. Env: OVERPASS_ENDPOINT. Mirrors: "
            "https://overpass.kumi.systems/api/interpreter, "
            "https://overpass.private.coffee/api/interpreter."
        ),
    )
    args = p.parse_args()

    try:
        data = fetch_overpass(
            args.bbox, user_agent=args.user_agent, endpoint=args.endpoint
        )
    except urllib.error.HTTPError as e:
        print(f"HTTP error: {e}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"Network error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Bad --bbox: {e}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    counts = _summarize(data)
    print(
        f"Wrote {args.output}: {counts['relation']} restriction relations, "
        f"{counts['way']} ways, {counts['node']} nodes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
