#!/usr/bin/env python3
"""Measure lane-count accuracy of ``infer-lane-count`` against OSM ``lanes=`` ground truth.

Workflow
--------
1. Fetch OSM highway ways for a bbox (``fetch_osm_highways.py --bbox ...``).
2. Build a graph: ``roadgraph_builder build-osm-graph raw.json --output graph.json ...``
3. Infer lane counts: ``roadgraph_builder infer-lane-count graph.json --output graph_lc.json``
4. Fetch OSM lanes ground truth (way ``lanes=`` tag) separately or use the same
   Overpass JSON — this script accepts both forms.
5. Run this script::

       python scripts/measure_lane_accuracy.py \\
           --graph graph_lc.json \\
           --osm-lanes-json raw_overpass.json \\
           --matching-tolerance-m 5.0 \\
           --output accuracy_result.json

The script matches graph edges to OSM ways by nearest-centerline proximity
(within ``--matching-tolerance-m``) and directional alignment (parallel tangents).
It then compares ``attributes.hd.lane_count`` against the OSM ``lanes=`` integer.

Output: JSON with ``confusion_matrix``, ``mae``, ``matched_edges``, ``unmatched_edges``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

# Allow running directly from the repo root without installing.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Geometry helpers (no external deps beyond stdlib)
# ---------------------------------------------------------------------------


def _polyline_centroid(polyline: list[list[float]]) -> tuple[float, float]:
    """Return the mean xy of a polyline (WGS84 or meter coords both work)."""
    xs = [p[0] for p in polyline]
    ys = [p[1] for p in polyline]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _polyline_tangent(polyline: list[list[float]]) -> tuple[float, float]:
    """Return the overall tangent vector (start → end), normalised."""
    if len(polyline) < 2:
        return (1.0, 0.0)
    dx = polyline[-1][0] - polyline[0][0]
    dy = polyline[-1][1] - polyline[0][1]
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return (1.0, 0.0)
    return dx / length, dy / length


def _haversine_approx_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Fast equirectangular approximation in metres (adequate for < 10 km)."""
    R = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    cos_lat = math.cos(math.radians((lat1 + lat2) / 2))
    return R * math.hypot(dlat, dlon * cos_lat)


def _centroid_distance_m(
    cx1: float, cy1: float, cx2: float, cy2: float, *, use_haversine: bool
) -> float:
    if use_haversine:
        return _haversine_approx_m(cy1, cx1, cy2, cx2)
    return math.hypot(cx2 - cx1, cy2 - cy1)


def _lonlat_to_meters(
    lon_deg: float, lat_deg: float, lat0_deg: float, lon0_deg: float
) -> tuple[float, float]:
    """Local ENU from origin (lat0, lon0); matches roadgraph_builder.utils.geo."""
    r = 6_371_000.0
    lat_r = math.radians(lat0_deg)
    x = r * math.radians(lon_deg - lon0_deg) * math.cos(lat_r)
    y = r * math.radians(lat_deg - lat0_deg)
    return x, y


# ---------------------------------------------------------------------------
# Core matching and accuracy logic
# ---------------------------------------------------------------------------


def measure_lane_accuracy(
    graph_json: dict[str, Any],
    osm_lanes_json: dict[str, Any],
    *,
    matching_tolerance_m: float = 5.0,
    min_alignment_cos: float = 0.7,
    use_haversine: bool = True,
) -> dict[str, Any]:
    """Match graph edges to OSM ways and compare lane counts.

    Args:
        graph_json: Road graph dict (schema_version, nodes, edges) with
            ``attributes.hd.lane_count`` populated by ``infer-lane-count``.
        osm_lanes_json: Raw Overpass JSON (``elements`` list containing
            ``way`` objects with a ``tags.lanes`` field).  Also accepts a
            pre-filtered dict ``{way_id: lane_count_int}``.
        matching_tolerance_m: Maximum centroid-to-centroid distance (metres)
            to consider a graph edge ↔ OSM way match.
        min_alignment_cos: Minimum absolute cosine similarity between the
            edge and way tangents.  Below this threshold the pair is rejected
            (prevents matching perpendicular one-ways on parallel streets).
        use_haversine: When True, treat coordinates as lon/lat degrees and
            apply an equirectangular approximation.  When False, treat as
            metres (graph already in local frame).

    Returns:
        Dict with keys:
        - ``confusion_matrix``: ``{actual: {predicted: count}}``
        - ``mae``: Mean absolute error on matched pairs.
        - ``matched_count``: Number of edges matched.
        - ``unmatched_count``: Number of edges with no OSM match.
        - ``pairs``: List of ``{edge_id, predicted, actual, distance_m}`` dicts.
    """
    # Parse OSM ways: support raw Overpass JSON or pre-parsed dict.
    osm_ways: dict[int, int] = {}  # way_id → lane_count
    osm_way_coords: dict[int, tuple[float, float]] = {}  # way_id → centroid (lon, lat)
    osm_way_tangents: dict[int, tuple[float, float]] = {}

    # When build-osm-graph writes metadata.map_origin, graph polylines are in
    # local meter frame — convert OSM node coords to the same frame so the
    # distance check is apples-to-apples.
    map_origin = None
    metadata = graph_json.get("metadata") if isinstance(graph_json, dict) else None
    if isinstance(metadata, dict):
        origin_meta = metadata.get("map_origin")
        if isinstance(origin_meta, dict) and "lat0" in origin_meta and "lon0" in origin_meta:
            try:
                map_origin = (float(origin_meta["lat0"]), float(origin_meta["lon0"]))
            except (TypeError, ValueError):
                map_origin = None
    if map_origin is not None:
        # Graph is in meters; override haversine flag to avoid mixed-frame compare.
        use_haversine = False

    if isinstance(osm_lanes_json, dict) and "elements" in osm_lanes_json:
        elements = osm_lanes_json["elements"]
    elif isinstance(osm_lanes_json, dict) and all(
        isinstance(k, (str, int)) for k in osm_lanes_json
    ):
        # Pre-parsed {way_id: lane_count} or {"centroid": [...], "lane_count": N} per way.
        # Try to treat as a flat mapping.
        for wid, val in osm_lanes_json.items():
            if isinstance(val, int):
                osm_ways[int(wid)] = val
        elements = []
    else:
        elements = []

    # Accumulate node coordinates from Overpass JSON for centroid computation.
    node_coords: dict[int, tuple[float, float]] = {}
    for el in elements:
        if not isinstance(el, dict):
            continue
        if el.get("type") == "node":
            nid = el.get("id")
            lat = el.get("lat")
            lon = el.get("lon")
            if nid is not None and lat is not None and lon is not None:
                lon_f = float(lon)
                lat_f = float(lat)
                if map_origin is not None:
                    node_coords[int(nid)] = _lonlat_to_meters(
                        lon_f, lat_f, map_origin[0], map_origin[1]
                    )
                else:
                    node_coords[int(nid)] = (lon_f, lat_f)

    for el in elements:
        if not isinstance(el, dict) or el.get("type") != "way":
            continue
        tags = el.get("tags", {})
        if not isinstance(tags, dict):
            continue
        lanes_raw = tags.get("lanes")
        if lanes_raw is None:
            continue
        try:
            lanes_int = int(lanes_raw)
        except (TypeError, ValueError):
            continue
        wid = int(el.get("id", -1))
        if wid < 0:
            continue
        osm_ways[wid] = lanes_int

        # Compute way centroid from its node refs.
        nds = el.get("nodes", [])
        if not isinstance(nds, list) or not nds:
            continue
        coords = [node_coords[n] for n in nds if n in node_coords]
        if len(coords) < 2:
            continue
        cx = sum(c[0] for c in coords) / len(coords)
        cy = sum(c[1] for c in coords) / len(coords)
        osm_way_coords[wid] = (cx, cy)

        # Tangent: first → last node.
        tx = coords[-1][0] - coords[0][0]
        ty = coords[-1][1] - coords[0][1]
        tlen = math.hypot(tx, ty)
        if tlen > 1e-12:
            osm_way_tangents[wid] = (tx / tlen, ty / tlen)
        else:
            osm_way_tangents[wid] = (1.0, 0.0)

    # Build list of (centroid, tangent, lane_count) for all OSM ways with data.
    osm_items: list[tuple[int, tuple[float, float], tuple[float, float], int]] = [
        (wid, osm_way_coords[wid], osm_way_tangents[wid], lc)
        for wid, lc in osm_ways.items()
        if wid in osm_way_coords
    ]

    # Extract graph edges with predicted lane_count.
    edges = graph_json.get("edges", [])
    pairs: list[dict[str, Any]] = []
    unmatched: int = 0

    for edge in edges:
        eid = edge.get("id", "?")
        attrs = edge.get("attributes", {})
        hd = attrs.get("hd", {}) if isinstance(attrs.get("hd"), dict) else {}
        predicted: int | None = hd.get("lane_count")
        if predicted is None:
            # Fallback: try top-level lane_count (some older output shapes).
            predicted = attrs.get("lane_count")
        if predicted is None:
            unmatched += 1
            continue

        polyline_raw = edge.get("polyline", [])
        if not polyline_raw:
            unmatched += 1
            continue

        poly_flat: list[list[float]] = []
        for pt in polyline_raw:
            if isinstance(pt, dict):
                poly_flat.append([float(pt.get("x", 0)), float(pt.get("y", 0))])
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                poly_flat.append([float(pt[0]), float(pt[1])])

        if len(poly_flat) < 2:
            unmatched += 1
            continue

        ecx, ecy = _polyline_centroid(poly_flat)
        etx, ety = _polyline_tangent(poly_flat)

        # Find nearest OSM way within tolerance.
        best_wid: int | None = None
        best_dist = float("inf")
        best_lanes: int = -1

        for wid, (wcx, wcy), (wtx, wty), wlanes in osm_items:
            dist = _centroid_distance_m(ecx, ecy, wcx, wcy, use_haversine=use_haversine)
            if dist > matching_tolerance_m:
                continue
            # Directional alignment (use abs to allow reversed directions).
            cos_sim = abs(etx * wtx + ety * wty)
            if cos_sim < min_alignment_cos:
                continue
            if dist < best_dist:
                best_dist = dist
                best_wid = wid
                best_lanes = wlanes

        if best_wid is None:
            unmatched += 1
            continue

        pairs.append(
            {
                "edge_id": str(eid),
                "predicted": int(predicted),
                "actual": best_lanes,
                "distance_m": round(best_dist, 3),
                "osm_way_id": best_wid,
            }
        )

    # Build confusion matrix and MAE.
    confusion: dict[str, dict[str, int]] = {}
    errors: list[float] = []
    for p in pairs:
        act = str(p["actual"])
        pred = str(p["predicted"])
        confusion.setdefault(act, {})
        confusion[act][pred] = confusion[act].get(pred, 0) + 1
        errors.append(abs(p["predicted"] - p["actual"]))

    mae = sum(errors) / len(errors) if errors else None

    return {
        "confusion_matrix": confusion,
        "mae": mae,
        "matched_count": len(pairs),
        "unmatched_count": unmatched,
        "pairs": pairs,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description="Measure infer-lane-count accuracy vs OSM lanes= ground truth."
    )
    p.add_argument(
        "--graph",
        required=True,
        type=Path,
        help="Road graph JSON with hd.lane_count populated (from infer-lane-count).",
    )
    p.add_argument(
        "--osm-lanes-json",
        required=True,
        type=Path,
        help="Raw Overpass JSON (highway ways with lanes= tags).",
    )
    p.add_argument(
        "--matching-tolerance-m",
        type=float,
        default=5.0,
        help="Max centroid-to-centroid distance in metres (default: 5.0).",
    )
    p.add_argument(
        "--min-alignment",
        type=float,
        default=0.7,
        help="Min abs cosine similarity for tangent alignment (default: 0.7).",
    )
    p.add_argument(
        "--no-haversine",
        action="store_true",
        help="Treat coordinates as metres instead of WGS84 lon/lat.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON result to this file (default: stdout).",
    )
    args = p.parse_args()

    if not args.graph.is_file():
        print(f"File not found: {args.graph}", file=sys.stderr)
        return 1
    if not args.osm_lanes_json.is_file():
        print(f"File not found: {args.osm_lanes_json}", file=sys.stderr)
        return 1

    graph_json = json.loads(args.graph.read_text(encoding="utf-8"))
    osm_json = json.loads(args.osm_lanes_json.read_text(encoding="utf-8"))

    result = measure_lane_accuracy(
        graph_json,
        osm_json,
        matching_tolerance_m=args.matching_tolerance_m,
        min_alignment_cos=args.min_alignment,
        use_haversine=not args.no_haversine,
    )

    out_str = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(out_str, encoding="utf-8")
        print(f"Wrote {args.output}")
        _print_summary(result)
    else:
        print(out_str)

    return 0


def _print_summary(result: dict[str, Any]) -> None:
    print(f"Matched edges: {result['matched_count']}")
    print(f"Unmatched edges: {result['unmatched_count']}")
    mae = result.get("mae")
    if mae is not None:
        print(f"MAE: {mae:.3f} lanes")
    print("Confusion matrix (actual→predicted):")
    for actual, preds in sorted(result["confusion_matrix"].items()):
        for pred, count in sorted(preds.items()):
            print(f"  actual={actual} predicted={pred}: {count}")


if __name__ == "__main__":
    raise SystemExit(main())
