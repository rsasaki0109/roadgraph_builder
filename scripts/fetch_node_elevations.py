#!/usr/bin/env python3
"""Fetch SRTM-class elevations for each graph node in a committed GeoJSON map.

Reads ``docs/assets/<dataset>.geojson`` (produced by the ``roadgraph_builder``
pipeline), extracts every ``kind=node`` Point feature's ``(lon, lat)``, and
POSTs the batch to the Open-Elevation public API at
``https://api.open-elevation.com/api/v1/lookup``. The response is stored as
``{node_id: elevation_m}`` JSON that ``scripts/refresh_docs_assets.py``
consumes to populate ``node.attributes.elevation_m`` and per-edge
``polyline_z``.

Open-Elevation is a free public service backed by NASA SRTM-30m; the
returned elevations are metres above mean sea level. Requests are rate-
limited, so this fetcher is meant to run once per dataset refresh, not
inside CI. Raw output goes to ``/tmp`` by repo convention.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_ENDPOINT = "https://api.open-elevation.com/api/v1/lookup"
DEFAULT_USER_AGENT = (
    "roadgraph_builder/0.7 (+https://github.com/rsasaki0109/roadgraph_builder)"
)
BATCH_SIZE = 500  # Open-Elevation recommends ≤ 1000 per POST.


def _collect_nodes(geojson_path: Path) -> list[tuple[str, float, float]]:
    doc = json.loads(geojson_path.read_text(encoding="utf-8"))
    out: list[tuple[str, float, float]] = []
    for feat in doc.get("features") or []:
        props = feat.get("properties") or {}
        if props.get("kind") != "node":
            continue
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        node_id = props.get("node_id")
        if not node_id:
            continue
        out.append((str(node_id), float(coords[1]), float(coords[0])))  # (id, lat, lon)
    return out


def _post_batch(
    batch: list[tuple[str, float, float]],
    *,
    endpoint: str,
    user_agent: str,
) -> list[dict]:
    payload = {
        "locations": [
            {"latitude": lat, "longitude": lon} for (_nid, lat, lon) in batch
        ]
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": user_agent,
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("results") or []


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--geojson", type=Path, required=True,
                   help="Map GeoJSON path (docs/assets/<dataset>.geojson)")
    p.add_argument("-o", "--output", type=Path, required=True,
                   help="Output JSON {node_id: elevation_m}.")
    p.add_argument("--endpoint", default=os.environ.get("ROADGRAPH_ELEVATION_ENDPOINT", DEFAULT_ENDPOINT))
    p.add_argument("--user-agent", default=os.environ.get("ROADGRAPH_USER_AGENT", DEFAULT_USER_AGENT))
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = p.parse_args()

    nodes = _collect_nodes(args.geojson)
    if not nodes:
        print(f"No graph nodes found in {args.geojson}", file=sys.stderr)
        return 1

    elevations: dict[str, float] = {}
    for i in range(0, len(nodes), args.batch_size):
        batch = nodes[i : i + args.batch_size]
        try:
            results = _post_batch(
                batch, endpoint=args.endpoint, user_agent=args.user_agent
            )
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            print(f"elevation fetch failed on batch {i}: {exc}", file=sys.stderr)
            return 2
        if len(results) != len(batch):
            print(
                f"unexpected response length for batch {i}: "
                f"{len(results)} vs {len(batch)}",
                file=sys.stderr,
            )
            return 3
        for (node_id, _lat, _lon), res in zip(batch, results):
            try:
                elevations[node_id] = float(res["elevation"])
            except (TypeError, ValueError, KeyError):
                continue

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "format_version": 1,
                "source": args.endpoint,
                "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
                "notes": (
                    "Elevation values are metres above mean sea level, "
                    "sourced from Open-Elevation's SRTM-30m dataset."
                ),
                "elevations": elevations,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {args.output} with {len(elevations)}/{len(nodes)} elevations",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
