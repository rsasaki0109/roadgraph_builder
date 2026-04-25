#!/usr/bin/env python3
"""Regenerate docs/assets and docs/images from examples/ (run after changing pipeline or samples)."""

from __future__ import annotations

import html
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
ASSETS = DOCS / "assets"
IMAGES = DOCS / "images"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_REPO_URL = "https://github.com/rsasaki0109/roadgraph_builder"
DEFAULT_PAGES_URL = "https://rsasaki0109.github.io/roadgraph_builder/"
PARIS_GRID_REACHABLE_START_NODE = "n312"
PARIS_GRID_REACHABLE_MAX_COST_M = 500.0
PARIS_GRID_ROUTE_FROM_NODE = "n312"
PARIS_GRID_ROUTE_TO_NODE = "n191"


def _load_origin(path: Path) -> tuple[float, float]:
    d = json.loads(path.read_text(encoding="utf-8"))
    return float(d["lat0"]), float(d["lon0"])


def _coords(line: object) -> list[tuple[float, float]]:
    if not isinstance(line, list):
        return []
    out: list[tuple[float, float]] = []
    for pt in line:
        if isinstance(pt, list) and len(pt) >= 2:
            out.append((float(pt[0]), float(pt[1])))
    return out


def _point_along_lonlat_polyline(
    coords: list[list[float]], fraction: float
) -> list[float] | None:
    if not coords:
        return None
    if len(coords) < 2:
        return list(coords[0])
    fraction = max(0.0, min(1.0, float(fraction)))
    total = 0.0
    segs: list[tuple[float, float, list[float], list[float]]] = []
    for a, b in zip(coords[:-1], coords[1:]):
        dx = float(b[0]) - float(a[0])
        dy = float(b[1]) - float(a[1])
        d = (dx * dx + dy * dy) ** 0.5
        segs.append((total, d, list(a), list(b)))
        total += d
    if total <= 0:
        return list(coords[0])
    target = total * fraction
    for start, length, a, b in segs:
        if start + length >= target:
            f = (target - start) / length if length > 0 else 0.0
            return [a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])]
    return list(coords[-1])


_SEMANTIC_KIND_FRACTIONS = {
    "traffic_light": 0.92,
    "stop_line": 0.85,
    "crosswalk": 0.5,
    "speed_limit": 0.5,
}


def _append_semantic_overlay_points(
    geojson: dict,
    detections_observations: list[dict],
    dataset_name: str,
) -> int:
    """Emit one Point feature per detection observation so the viewer can
    render a visible marker (traffic light / stop line / crosswalk / speed
    limit) at a sensible spot along the owning centerline. Returns the
    number of markers added.
    """
    edge_lookup: dict[str, list[list[float]]] = {}
    for feat in geojson.get("features", []):
        props = feat.get("properties") or {}
        if props.get("kind") not in ("centerline", "lane_centerline"):
            continue
        eid = props.get("edge_id")
        geom = feat.get("geometry") or {}
        if not eid or geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) >= 2:
            edge_lookup[str(eid)] = coords
    added = 0
    for obs in detections_observations:
        eid = obs.get("edge_id")
        kind = obs.get("kind")
        if not eid or not kind:
            continue
        coords = edge_lookup.get(str(eid))
        if not coords:
            continue
        fraction = _SEMANTIC_KIND_FRACTIONS.get(str(kind), 0.5)
        pos = _point_along_lonlat_polyline(coords, fraction)
        if pos is None:
            continue
        props: dict[str, object] = {
            "kind": str(kind),
            "dataset": dataset_name,
            "edge_id": str(eid),
        }
        for k in ("value_kmh", "confidence", "source"):
            if k in obs and obs[k] is not None:
                props[k] = obs[k]
        geojson["features"].append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Point", "coordinates": pos},
            }
        )
        added += 1
    return added


def _collect_osm_way_polylines(
    overpass_json: dict,
    origin_lat: float,
    origin_lon: float,
    wanted: frozenset[str],
) -> list[dict]:
    """Return per-way OSM metadata + meter-frame polyline for nearest-edge
    matching. One OSM way may map to many graph edges (because X/T
    junction splitting subdivides a way), so we attach tags back per edge
    rather than per way.
    """
    from roadgraph_builder.utils.geo import lonlat_to_meters

    nodes_ll: dict[int, tuple[float, float]] = {}
    ways: list[dict] = []
    for el in overpass_json.get("elements") or []:
        kind = el.get("type")
        if kind == "node":
            nid = el.get("id")
            lat = el.get("lat")
            lon = el.get("lon")
            if isinstance(nid, int) and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                nodes_ll[int(nid)] = (float(lon), float(lat))
        elif kind == "way":
            ways.append(el)
    out: list[dict] = []
    for way in ways:
        tags = way.get("tags") or {}
        if not isinstance(tags, dict):
            tags = {}
        hwy = tags.get("highway")
        if not isinstance(hwy, str) or hwy not in wanted:
            continue
        refs = way.get("nodes") or []
        coords_m: list[tuple[float, float]] = []
        for r in refs:
            if not isinstance(r, int):
                continue
            ll = nodes_ll.get(r)
            if ll is None:
                continue
            x, y = lonlat_to_meters(ll[0], ll[1], origin_lat, origin_lon)
            coords_m.append((x, y))
        if len(coords_m) < 2:
            continue
        out.append(
            {
                "tags": {
                    "highway": hwy,
                    "lanes": tags.get("lanes"),
                    "maxspeed": tags.get("maxspeed"),
                    "oneway": tags.get("oneway"),
                    "name": tags.get("name"),
                    "width": tags.get("width"),
                },
                "coords_m": coords_m,
            }
        )
    return out


def _point_to_polyline_distance_m(
    px: float, py: float, polyline: list[tuple[float, float]]
) -> float:
    best = float("inf")
    if len(polyline) < 2:
        return best
    for i in range(len(polyline) - 1):
        x1, y1 = polyline[i]
        x2, y2 = polyline[i + 1]
        dx = x2 - x1
        dy = y2 - y1
        denom = dx * dx + dy * dy
        if denom <= 0:
            ex = px - x1
            ey = py - y1
        else:
            t = ((px - x1) * dx + (py - y1) * dy) / denom
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            qx = x1 + t * dx
            qy = y1 + t * dy
            ex = px - qx
            ey = py - qy
        d2 = ex * ex + ey * ey
        if d2 < best:
            best = d2
    return best ** 0.5 if best < float("inf") else best


def _osm_regulatory_kind_from_tags(tags: dict) -> str | None:
    """Map an OSM node's ``highway=*`` tag to the edge-keyed semantic kind
    the rest of the pipeline uses.

    Returns None when the node is not a regulatory signal we know how to
    project onto a graph edge.
    """
    if not isinstance(tags, dict):
        return None
    hwy = tags.get("highway")
    if not isinstance(hwy, str):
        return None
    match hwy:
        case "traffic_signals":
            return "traffic_light"
        case "stop":
            return "stop_line"
        case "give_way":
            return "stop_line"
        case "crossing":
            return "crosswalk"
        case "speed_camera":
            return "speed_camera"
    return None


def _osm_regulatory_observations(
    overpass_regulatory_json: dict,
    graph,
    origin_lat: float,
    origin_lon: float,
    *,
    max_match_distance_m: float = 20.0,
    max_crossings: int | None = 160,
) -> list[dict]:
    """Project OSM regulatory nodes (``highway=traffic_signals|stop|crossing|...``)
    onto the nearest graph edge and return camera-detections-style observations
    with ``source="osm_node"``. ``max_crossings`` keeps the overlay count sane
    when the bbox has thousands of pedestrian crossings — set to ``None`` to
    disable the cap.
    """
    from roadgraph_builder.utils.geo import lonlat_to_meters

    elements = overpass_regulatory_json.get("elements") or []
    edge_polys: list[tuple[str, list[tuple[float, float]]]] = []
    for edge in graph.edges:
        poly = [(float(x), float(y)) for x, y in edge.polyline]
        if len(poly) >= 2:
            edge_polys.append((edge.id, poly))
    if not edge_polys:
        return []

    observations: list[dict] = []
    crossing_count = 0
    for el in elements:
        if not isinstance(el, dict) or el.get("type") != "node":
            continue
        tags = el.get("tags") or {}
        kind = _osm_regulatory_kind_from_tags(tags)
        if kind is None:
            continue
        if kind == "crosswalk" and max_crossings is not None:
            if crossing_count >= max_crossings:
                continue
        lat = el.get("lat")
        lon = el.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        x, y = lonlat_to_meters(float(lon), float(lat), origin_lat, origin_lon)
        best_edge = None
        best_d = max_match_distance_m
        for eid, poly in edge_polys:
            d = _point_to_polyline_distance_m(x, y, poly)
            if d < best_d:
                best_d = d
                best_edge = eid
        if best_edge is None:
            continue
        obs: dict = {
            "edge_id": best_edge,
            "kind": kind,
            "source": "osm_node",
            "osm_id": el.get("id"),
            "confidence": 1.0,
            "match_distance_m": round(best_d, 3),
            # world_xy_m anchors the regulatory element at the OSM node's
            # location so `_build_traffic_light_regulatory` (Lanelet2 export)
            # can emit an XYZ-positioned traffic_light node instead of
            # falling back to the edge endpoint.
            "world_xy_m": {"x": round(x, 3), "y": round(y, 3)},
        }
        if kind == "speed_camera" and "maxspeed" in tags:
            try:
                obs["value_kmh"] = int(float(str(tags["maxspeed"]).split()[0]))
            except (TypeError, ValueError):
                pass
        observations.append(obs)
        if kind == "crosswalk":
            crossing_count += 1
    return observations


def _apply_node_elevations(graph, elevations: dict[str, float]) -> int:
    """Stamp ``node.attributes.elevation_m`` + per-edge ``polyline_z`` from a
    precomputed ``{node_id: elevation_m}`` mapping (typically produced by
    ``scripts/fetch_node_elevations.py`` against Open-Elevation / SRTM).

    Each edge's ``polyline_z`` is a linear interpolation between its start-
    and end-node elevations, so ``enrich_sd_to_hd`` can compute
    ``hd.slope_deg`` downstream and the Lanelet2 exporter emits ``ele`` tags
    on graph nodes. Returns the number of nodes with elevation applied.
    """
    applied = 0
    for node in graph.nodes:
        z = elevations.get(str(node.id))
        if z is None:
            continue
        attrs = dict(node.attributes)
        attrs["elevation_m"] = float(z)
        node.attributes = attrs
        applied += 1
    if not applied:
        return 0
    # Per-edge polyline_z via linear interpolation along cumulative meter length.
    import math

    for edge in graph.edges:
        start_z = elevations.get(str(edge.start_node_id))
        end_z = elevations.get(str(edge.end_node_id))
        if start_z is None or end_z is None:
            continue
        pl = edge.polyline
        if len(pl) < 2:
            continue
        cum = [0.0]
        for i in range(1, len(pl)):
            dx = pl[i][0] - pl[i - 1][0]
            dy = pl[i][1] - pl[i - 1][1]
            cum.append(cum[-1] + math.hypot(dx, dy))
        total = cum[-1]
        if total <= 0:
            polyline_z = [float(start_z)] * len(pl)
        else:
            polyline_z = [
                float(start_z) + (float(end_z) - float(start_z)) * (c / total)
                for c in cum
            ]
        attrs = dict(edge.attributes)
        attrs["polyline_z"] = polyline_z
        edge.attributes = attrs
    return applied


def _widen_hd_envelope_for_osm_lanes(graph, base_lane_width_m: float = 3.5) -> int:
    """Widen the HD-lite ``hd.lane_boundaries`` envelope on edges that carry
    an OSM ``width`` (most accurate) or ``lanes`` tag so the outermost paint
    lines reflect the real road width instead of the single-lane default
    produced by :func:`enrich_sd_to_hd`.

    Precedence for the total road width:
      * ``osm_width_m`` (direct OSM ``width=`` tag, metres)
      * ``osm_lanes * base_lane_width_m`` (derived from OSM ``lanes=`` tag)
      * otherwise, leave the default single-lane envelope untouched

    Returns the number of edges whose envelope was rewritten.
    """
    from roadgraph_builder.hd.boundaries import (
        centerline_lane_boundaries,
        polyline_to_json_points,
    )

    widened = 0
    for edge in graph.edges:
        attrs = dict(edge.attributes)
        width_raw = attrs.get("osm_width_m")
        osm_width_m: float | None = None
        if isinstance(width_raw, (int, float)) and float(width_raw) > 0:
            osm_width_m = float(width_raw)
        lanes_n = attrs.get("osm_lanes")
        if osm_width_m is not None:
            total_width = osm_width_m
            source_tag = "osm_width_tag"
            note = (
                f"Outer paint envelope uses OSM width={osm_width_m} m; "
                "HD-lite, not survey-grade."
            )
        elif isinstance(lanes_n, int) and lanes_n >= 2:
            total_width = base_lane_width_m * float(lanes_n)
            source_tag = "osm_lanes_offset_hd_lite"
            note = (
                f"Outer paint envelope offset by {lanes_n}x {base_lane_width_m} m "
                "from centerline (OSM lanes tag); HD-lite, not survey-grade."
            )
        else:
            continue
        left, right = centerline_lane_boundaries(edge.polyline, total_width)
        if not left or not right:
            continue
        hd = dict(attrs.get("hd") or {})
        hd["lane_boundaries"] = {
            "left": polyline_to_json_points(left),
            "right": polyline_to_json_points(right),
        }
        hd["quality"] = source_tag
        hd["note"] = note
        attrs["hd"] = hd
        edge.attributes = attrs
        widened += 1
    return widened


def _inject_osm_tags_into_graph_edges(
    graph,
    origin_lat: float,
    origin_lon: float,
    way_specs: list[dict],
    max_match_distance_m: float = 8.0,
) -> int:
    """Stamp OSM highway / lanes / maxspeed / name tags onto ``edge.attributes``
    by nearest point-to-polyline match. Because
    :func:`export_map_geojson` spreads ``edge.attributes`` into the exported
    feature properties, downstream Lanelet2 / GeoJSON / sd_nav exporters all
    see the same stamped values. Returns the number of matched edges.
    """
    stamped = 0
    for edge in graph.edges:
        poly = edge.polyline
        if len(poly) < 2:
            continue
        mid = poly[len(poly) // 2]
        px, py = float(mid[0]), float(mid[1])
        best = None
        best_d = max_match_distance_m
        for spec in way_specs:
            d = _point_to_polyline_distance_m(px, py, spec["coords_m"])
            if d < best_d:
                best_d = d
                best = spec
        if best is None:
            continue
        tags = best["tags"]
        attrs = dict(edge.attributes)
        if tags.get("highway"):
            attrs["highway"] = str(tags["highway"])
        if tags.get("lanes"):
            lanes_raw = str(tags["lanes"]).strip()
            try:
                lanes_int = int(lanes_raw)
            except ValueError:
                lanes_int = None
            if lanes_int is not None and lanes_int > 0:
                attrs["osm_lanes"] = lanes_int
        if tags.get("maxspeed"):
            attrs["osm_maxspeed"] = str(tags["maxspeed"])
        if tags.get("oneway"):
            attrs["osm_oneway"] = str(tags["oneway"])
        if tags.get("name"):
            attrs["osm_name"] = str(tags["name"])
        width_raw = tags.get("width")
        if width_raw is not None:
            try:
                width_val = float(str(width_raw).strip().split()[0])
                if width_val > 0:
                    attrs["osm_width_m"] = round(width_val, 3)
            except (TypeError, ValueError):
                pass
        edge.attributes = attrs
        stamped += 1
    return stamped


def _inject_osm_tags_into_geojson(
    geojson: dict,
    origin_lat: float,
    origin_lon: float,
    way_specs: list[dict],
    max_match_distance_m: float = 8.0,
) -> dict:
    """Stamp OSM highway / lanes / maxspeed / oneway / name tags onto every
    centerline / lane_centerline feature by nearest point-to-polyline match
    in the shared meter frame. Mutates ``geojson["features"]`` in place and
    returns ``geojson`` for chaining.
    """
    from roadgraph_builder.utils.geo import lonlat_to_meters

    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        kind = props.get("kind")
        if kind not in ("centerline", "lane_centerline"):
            continue
        geom = feature.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        mid = coords[len(coords) // 2]
        if not isinstance(mid, list) or len(mid) < 2:
            continue
        px, py = lonlat_to_meters(float(mid[0]), float(mid[1]), origin_lat, origin_lon)
        best = None
        best_d = max_match_distance_m
        for spec in way_specs:
            d = _point_to_polyline_distance_m(px, py, spec["coords_m"])
            if d < best_d:
                best_d = d
                best = spec
        if best is None:
            continue
        tags = best["tags"]
        if tags.get("highway"):
            props["highway"] = str(tags["highway"])
        if tags.get("lanes"):
            lanes_raw = str(tags["lanes"]).strip()
            try:
                lanes_int = int(lanes_raw)
            except ValueError:
                lanes_int = None
            if lanes_int is not None and lanes_int > 0:
                props["osm_lanes"] = lanes_int
        if tags.get("maxspeed"):
            props["osm_maxspeed"] = str(tags["maxspeed"])
        if tags.get("oneway"):
            props["osm_oneway"] = str(tags["oneway"])
        if tags.get("name"):
            props["osm_name"] = str(tags["name"])
    return geojson


_OSM_WANTED_HIGHWAYS = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
        "service",
        "road",
    }
)


def _graph_from_map_geojson(path: Path):
    """Rebuild a meter-frame Graph from a committed map GeoJSON asset."""

    from roadgraph_builder.core.graph.edge import Edge
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.core.graph.node import Node
    from roadgraph_builder.utils.geo import lonlat_to_meters

    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    props = doc.get("properties", {})
    if not isinstance(props, dict):
        return None
    try:
        origin_lat = float(props["origin_lat"])
        origin_lon = float(props["origin_lon"])
    except (KeyError, TypeError, ValueError):
        return None

    nodes: list[Node] = []
    edges: list[Edge] = []
    for feature in doc.get("features", []):
        if not isinstance(feature, dict):
            continue
        f_props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        if not isinstance(f_props, dict) or not isinstance(geom, dict):
            continue
        if f_props.get("kind") == "node":
            coords = geom.get("coordinates")
            node_id = f_props.get("node_id")
            if isinstance(coords, list) and len(coords) >= 2 and isinstance(node_id, str):
                nodes.append(
                    Node(
                        node_id,
                        lonlat_to_meters(
                            float(coords[0]),
                            float(coords[1]),
                            origin_lat,
                            origin_lon,
                        ),
                    )
                )
            continue
        if f_props.get("kind") != "centerline" or geom.get("type") != "LineString":
            continue
        edge_id = f_props.get("edge_id")
        start = f_props.get("start_node_id")
        end = f_props.get("end_node_id")
        if not (isinstance(edge_id, str) and isinstance(start, str) and isinstance(end, str)):
            continue
        polyline = [
            lonlat_to_meters(lon, lat, origin_lat, origin_lon)
            for lon, lat in _coords(geom.get("coordinates"))
        ]
        if len(polyline) >= 2:
            edges.append(Edge(edge_id, start, end, polyline))
    if not nodes or not edges:
        return None
    return Graph(nodes, edges)


def _route_explain_document(
    *,
    sample_id: str,
    label: str,
    source: str,
    command: str | None,
    route,
    diagnostics,
    restrictions_count: int,
) -> dict[str, object]:
    return {
        "id": sample_id,
        "label": label,
        "source": source,
        "command": command,
        "from_node": route.from_node,
        "to_node": route.to_node,
        "total_length_m": route.total_length_m,
        "edge_sequence": route.edge_sequence,
        "edge_directions": route.edge_directions,
        "node_sequence": route.node_sequence,
        "applied_restrictions": restrictions_count,
        "diagnostics": diagnostics.to_dict(),
    }


def _write_route_explain_sample_asset() -> None:
    """Write real route diagnostics examples for README / Pages snippets."""

    from roadgraph_builder.io.export.json_loader import load_graph_json
    from roadgraph_builder.navigation.turn_restrictions import load_turn_restrictions_json
    from roadgraph_builder.routing.shortest_path import RoutePlanner

    samples: list[dict[str, object]] = []

    frozen_graph = ROOT / "examples" / "frozen_bundle" / "sim" / "road_graph.json"
    if frozen_graph.is_file():
        graph = load_graph_json(frozen_graph)
        planner = RoutePlanner(graph)
        route = planner.shortest_path("n0", "n1")
        if planner.last_diagnostics is not None:
            samples.append(
                _route_explain_document(
                    sample_id="metric_sample_astar",
                    label="Metric sample route using safe A*",
                    source="examples/frozen_bundle/sim/road_graph.json",
                    command=(
                        "roadgraph_builder route "
                        "examples/frozen_bundle/sim/road_graph.json n0 n1 --explain"
                    ),
                    route=route,
                    diagnostics=planner.last_diagnostics,
                    restrictions_count=0,
                )
            )

    paris_graph = _graph_from_map_geojson(ASSETS / "map_paris_grid.geojson")
    restrictions_path = ASSETS / "paris_grid_turn_restrictions.json"
    if paris_graph is not None and restrictions_path.is_file():
        restrictions = load_turn_restrictions_json(restrictions_path)
        planner = RoutePlanner(paris_graph, turn_restrictions=restrictions)
        route = planner.shortest_path(PARIS_GRID_ROUTE_FROM_NODE, PARIS_GRID_ROUTE_TO_NODE)
        if planner.last_diagnostics is not None:
            samples.append(
                _route_explain_document(
                    sample_id="paris_grid_dijkstra_fallback",
                    label="Paris TR-aware route with safe Dijkstra fallback",
                    source="docs/assets/map_paris_grid.geojson",
                    command=None,
                    route=route,
                    diagnostics=planner.last_diagnostics,
                    restrictions_count=len(restrictions),
                )
            )

    if not samples:
        return
    doc = {
        "schema_version": 1,
        "generated_by": "scripts/refresh_docs_assets.py",
        "description": "RoutePlanner diagnostics examples shown in README and GitHub Pages.",
        "attribution": "Paris sample derived from OpenStreetMap data © OpenStreetMap contributors.",
        "license": "ODbL-1.0 for the Paris OSM-derived sample; MIT for generated project code.",
        "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "samples": samples,
    }
    (ASSETS / "route_explain_sample.json").write_text(
        json.dumps(doc, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_map_match_explain_sample_asset() -> None:
    """Write map-matching diagnostics examples for README / Showcase snippets."""

    from roadgraph_builder.cli.trajectory import (
        add_match_diagnostics,
        hmm_matches_to_document,
        match_trajectory_diagnostics,
        snapped_matches_to_document,
    )
    from roadgraph_builder.io.export.json_loader import load_graph_json
    from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
    from roadgraph_builder.routing.hmm_match import hmm_match_trajectory
    from roadgraph_builder.routing.map_match import coverage_stats, snap_trajectory_to_graph

    graph_path = ROOT / "examples" / "frozen_bundle" / "sim" / "road_graph.json"
    traj_path = ROOT / "examples" / "sample_trajectory.csv"
    if not (graph_path.is_file() and traj_path.is_file()):
        return

    graph = load_graph_json(graph_path)
    traj = load_trajectory_csv(traj_path)
    max_distance_m = 5.0

    nearest = snap_trajectory_to_graph(graph, traj.xy, max_distance_m=max_distance_m)
    nearest_doc = add_match_diagnostics(
        snapped_matches_to_document(nearest, coverage_stats_func=coverage_stats),
        match_trajectory_diagnostics(
            graph,
            algorithm="nearest_edge",
            sample_count=len(traj.xy),
            matched_count=sum(sample is not None for sample in nearest),
            max_distance_m=max_distance_m,
            elapsed_s=0.0,
        ),
    )

    hmm = hmm_match_trajectory(
        graph,
        traj.xy,
        candidate_radius_m=max_distance_m,
        gps_sigma_m=5.0,
        transition_limit_m=200.0,
    )
    hmm_doc = add_match_diagnostics(
        hmm_matches_to_document(hmm),
        match_trajectory_diagnostics(
            graph,
            algorithm="hmm_viterbi",
            sample_count=len(traj.xy),
            matched_count=sum(sample is not None for sample in hmm),
            max_distance_m=max_distance_m,
            elapsed_s=0.0,
        ),
    )

    doc = {
        "schema_version": 1,
        "generated_by": "scripts/refresh_docs_assets.py",
        "description": "Map matching --explain examples shown in README and Showcase.",
        "source_graph": "examples/frozen_bundle/sim/road_graph.json",
        "source_trajectory": "examples/sample_trajectory.csv",
        "elapsed_ms_note": "elapsed_ms is normalized to 0.0 in this committed docs asset for stable diffs.",
        "samples": [
            {
                "id": "toy_nearest_edge",
                "label": "Toy trajectory nearest-edge projection with edge-index diagnostics",
                "command": (
                    "roadgraph_builder match-trajectory "
                    "examples/frozen_bundle/sim/road_graph.json "
                    "examples/sample_trajectory.csv --max-distance-m 5 --explain"
                ),
                "result": nearest_doc,
            },
            {
                "id": "toy_hmm_viterbi",
                "label": "Toy trajectory HMM/Viterbi map matching with indexed candidates",
                "command": (
                    "roadgraph_builder match-trajectory "
                    "examples/frozen_bundle/sim/road_graph.json "
                    "examples/sample_trajectory.csv --max-distance-m 5 --hmm --explain"
                ),
                "result": hmm_doc,
            },
        ],
    }
    (ASSETS / "map_match_explain_sample.json").write_text(
        json.dumps(doc, indent=2) + "\n",
        encoding="utf-8",
    )


def _clip_line_fraction(
    line: list[tuple[float, float]],
    fraction: float,
) -> list[tuple[float, float]]:
    """Return the prefix of a lon/lat LineString by geometric fraction."""

    if not line:
        return []
    if fraction >= 1.0:
        return list(line)
    if fraction <= 0.0:
        return [line[0]]

    total = 0.0
    for i in range(len(line) - 1):
        x0, y0 = line[i]
        x1, y1 = line[i + 1]
        total += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    if total <= 0.0:
        return list(line)

    target = total * fraction
    walked = 0.0
    out = [line[0]]
    for i in range(len(line) - 1):
        x0, y0 = line[i]
        x1, y1 = line[i + 1]
        segment = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if segment <= 0.0:
            continue
        if walked + segment >= target:
            t = (target - walked) / segment
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
            return out
        out.append(line[i + 1])
        walked += segment
    return out


def _write_paris_grid_reachability_asset() -> None:
    """Build a committed service-area overlay from the Paris grid GeoJSON."""

    import heapq
    import itertools
    import math

    map_path = ASSETS / "map_paris_grid.geojson"
    restrictions_path = ASSETS / "paris_grid_turn_restrictions.json"
    if not (map_path.is_file() and restrictions_path.is_file()):
        return

    map_doc = json.loads(map_path.read_text(encoding="utf-8"))
    restrictions_doc = json.loads(restrictions_path.read_text(encoding="utf-8"))
    nodes: dict[str, tuple[float, float]] = {}
    edges: dict[str, dict[str, object]] = {}
    adj: dict[str, list[tuple[str, str, str, float]]] = {}

    for feature in map_doc.get("features", []):
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        if not isinstance(props, dict) or not isinstance(geom, dict):
            continue
        if props.get("kind") == "node":
            coords = geom.get("coordinates")
            node_id = props.get("node_id")
            if isinstance(coords, list) and len(coords) >= 2 and isinstance(node_id, str):
                nodes[node_id] = (float(coords[0]), float(coords[1]))
            continue
        if props.get("kind") not in {"centerline", "lane_centerline"}:
            continue
        edge_id = props.get("edge_id")
        start = props.get("start_node_id")
        end = props.get("end_node_id")
        length = props.get("length_m")
        if not (
            isinstance(edge_id, str)
            and isinstance(start, str)
            and isinstance(end, str)
            and isinstance(length, (int, float))
            and geom.get("type") == "LineString"
        ):
            continue
        line = _coords(geom.get("coordinates"))
        if len(line) < 2:
            continue
        length_m = float(length)
        edges[edge_id] = {"coords": line, "start": start, "end": end, "length_m": length_m}
        adj.setdefault(start, []).append((edge_id, "forward", end, length_m))
        if start != end:
            adj.setdefault(end, []).append((edge_id, "reverse", start, length_m))

    start_node = PARIS_GRID_REACHABLE_START_NODE
    budget = PARIS_GRID_REACHABLE_MAX_COST_M
    if start_node not in nodes:
        return

    no_turns: dict[tuple[str, str, str], set[tuple[str, str]]] = {}
    only_turns: dict[tuple[str, str, str], tuple[str, str]] = {}
    restrictions = restrictions_doc.get("turn_restrictions", [])
    if not isinstance(restrictions, list):
        restrictions = []
    for restriction in restrictions:
        if not isinstance(restriction, dict):
            continue
        junction = restriction.get("junction_node_id")
        from_edge = restriction.get("from_edge_id")
        to_edge = restriction.get("to_edge_id")
        if not (isinstance(junction, str) and isinstance(from_edge, str) and isinstance(to_edge, str)):
            continue
        from_dir = str(restriction.get("from_direction", "forward"))
        to_dir = str(restriction.get("to_direction", "forward"))
        key = (junction, from_edge, from_dir)
        target = (to_edge, to_dir)
        kind = str(restriction.get("restriction", ""))
        if kind.startswith("only_"):
            only_turns[key] = target
        elif kind.startswith("no_"):
            no_turns.setdefault(key, set()).add(target)

    State = tuple[str, str | None, str | None]
    start_state: State = (start_node, None, None)
    dist: dict[State, float] = {start_state: 0.0}
    best_node_cost: dict[str, float] = {start_node: 0.0}
    spans: dict[tuple[str, str], dict[str, object]] = {}
    counter = itertools.count()
    heap: list[tuple[float, int, State]] = [(0.0, next(counter), start_state)]

    while heap:
        cost, _, state = heapq.heappop(heap)
        if cost > dist.get(state, math.inf) or cost > budget:
            continue
        node_id, incoming_edge, incoming_dir = state
        for edge_id, direction, neighbor, edge_cost in adj.get(node_id, []):
            if incoming_edge is not None:
                from_key = (node_id, incoming_edge, str(incoming_dir))
                to_key = (edge_id, direction)
                if from_key in only_turns and only_turns[from_key] != to_key:
                    continue
                if to_key in no_turns.get(from_key, set()):
                    continue
            remaining = budget - cost
            if remaining > 0.0:
                fraction = 1.0 if edge_cost <= 0.0 else max(0.0, min(1.0, remaining / edge_cost))
                span_key = (edge_id, direction)
                current = spans.get(span_key)
                if (
                    current is None
                    or fraction > float(current["reachable_fraction"]) + 1e-12
                    or (
                        math.isclose(fraction, float(current["reachable_fraction"]))
                        and cost < float(current["start_cost_m"])
                    )
                ):
                    complete = cost + edge_cost <= budget
                    spans[span_key] = {
                        "edge_id": edge_id,
                        "direction": direction,
                        "from_node": node_id,
                        "to_node": neighbor,
                        "start_cost_m": cost,
                        "end_cost_m": cost + edge_cost if complete else None,
                        "reachable_cost_m": min(edge_cost, remaining),
                        "reachable_fraction": fraction,
                        "complete": complete,
                    }
            next_cost = cost + edge_cost
            if next_cost > budget:
                continue
            next_state: State = (neighbor, edge_id, direction)
            if next_cost < dist.get(next_state, math.inf):
                dist[next_state] = next_cost
                best_node_cost[neighbor] = min(best_node_cost.get(neighbor, math.inf), next_cost)
                heapq.heappush(heap, (next_cost, next(counter), next_state))

    features: list[dict[str, object]] = []
    for span in sorted(spans.values(), key=lambda s: (float(s["start_cost_m"]), str(s["edge_id"]), str(s["direction"]))):
        edge = edges[str(span["edge_id"])]
        line = list(edge["coords"])  # type: ignore[arg-type]
        if span["direction"] == "reverse":
            line.reverse()
        clipped = _clip_line_fraction(line, float(span["reachable_fraction"]))
        if len(clipped) < 2:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {"kind": "reachable_edge", **span},
                "geometry": {"type": "LineString", "coordinates": clipped},
            }
        )
    for node_id, cost in sorted(best_node_cost.items(), key=lambda item: (item[1], item[0])):
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "reachability_start" if node_id == start_node else "reachable_node",
                    "node_id": node_id,
                    "cost_m": cost,
                },
                "geometry": {"type": "Point", "coordinates": nodes[node_id]},
            }
        )

    doc = {
        "type": "FeatureCollection",
        "name": f"reachable_paris_grid_{start_node}_{budget:g}m",
        "properties": {
            "attribution": "© OpenStreetMap contributors",
            "license": "ODbL-1.0",
            "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
            "source_map": "map_paris_grid.geojson",
            "turn_restrictions": "paris_grid_turn_restrictions.json",
            "start_node": start_node,
            "max_cost_m": budget,
            "node_count": len(best_node_cost),
            "edge_count": len(spans),
            "complete_edge_count": sum(1 for span in spans.values() if span["complete"]),
        },
        "features": features,
    }
    (ASSETS / "reachable_paris_grid.geojson").write_text(
        json.dumps(doc, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _render_paris_grid_route_preview() -> None:
    """Render a static SVG preview for README / GitHub Pages."""
    map_path = ASSETS / "map_paris_grid.geojson"
    route_path = ASSETS / "route_paris_grid.geojson"
    reachable_path = ASSETS / "reachable_paris_grid.geojson"
    restrictions_path = ASSETS / "paris_grid_turn_restrictions.json"
    if not (map_path.is_file() and route_path.is_file() and restrictions_path.is_file()):
        return

    map_doc = json.loads(map_path.read_text(encoding="utf-8"))
    route_doc = json.loads(route_path.read_text(encoding="utf-8"))
    reachable_doc = (
        json.loads(reachable_path.read_text(encoding="utf-8"))
        if reachable_path.is_file()
        else {"features": [], "properties": {}}
    )
    restrictions_doc = json.loads(restrictions_path.read_text(encoding="utf-8"))

    centerlines: list[list[tuple[float, float]]] = []
    nodes: dict[str, tuple[float, float]] = {}
    reachable_lines: list[tuple[list[tuple[float, float]], bool]] = []
    reachable_start: tuple[float, float] | None = None
    route_lines: list[list[tuple[float, float]]] = []
    route_main: list[tuple[float, float]] = []
    start_pt: tuple[float, float] | None = None
    end_pt: tuple[float, float] | None = None

    for feature in map_doc.get("features", []):
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        if not isinstance(props, dict) or not isinstance(geom, dict):
            continue
        kind = props.get("kind")
        if kind == "centerline":
            line = _coords(geom.get("coordinates"))
            if len(line) >= 2:
                centerlines.append(line)
        elif kind == "node":
            coords = geom.get("coordinates")
            node_id = props.get("node_id")
            if isinstance(coords, list) and len(coords) >= 2 and isinstance(node_id, str):
                nodes[node_id] = (float(coords[0]), float(coords[1]))

    for feature in reachable_doc.get("features", []):
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        if not isinstance(props, dict) or not isinstance(geom, dict):
            continue
        kind = props.get("kind")
        if kind == "reachable_edge" and geom.get("type") == "LineString":
            line = _coords(geom.get("coordinates"))
            if len(line) >= 2:
                reachable_lines.append((line, bool(props.get("complete"))))
        elif kind == "reachability_start" and geom.get("type") == "Point":
            coords = geom.get("coordinates")
            if isinstance(coords, list) and len(coords) >= 2:
                reachable_start = (float(coords[0]), float(coords[1]))

    for feature in route_doc.get("features", []):
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        if not isinstance(props, dict) or not isinstance(geom, dict):
            continue
        kind = props.get("kind")
        if geom.get("type") == "LineString":
            line = _coords(geom.get("coordinates"))
            if len(line) >= 2:
                if kind == "route":
                    route_main = line
                elif kind == "route_edge":
                    route_lines.append(line)
        elif geom.get("type") == "Point":
            coords = geom.get("coordinates")
            if isinstance(coords, list) and len(coords) >= 2:
                pt = (float(coords[0]), float(coords[1]))
                if kind == "route_start":
                    start_pt = pt
                elif kind == "route_end":
                    end_pt = pt

    all_points: list[tuple[float, float]] = []
    for line in centerlines:
        all_points.extend(line)
    if not all_points:
        return

    min_x = min(p[0] for p in all_points)
    max_x = max(p[0] for p in all_points)
    min_y = min(p[1] for p in all_points)
    max_y = max(p[1] for p in all_points)
    width, height = 1200.0, 720.0
    pad_l, pad_r, pad_t, pad_b = 70.0, 340.0, 54.0, 70.0
    scale = min(
        (width - pad_l - pad_r) / (max_x - min_x),
        (height - pad_t - pad_b) / (max_y - min_y),
    )

    def project(pt: tuple[float, float]) -> tuple[float, float]:
        x, y = pt
        px = pad_l + (x - min_x) * scale
        py = height - pad_b - (y - min_y) * scale
        return px, py

    def path_d(line: list[tuple[float, float]]) -> str:
        pts = [project(p) for p in line]
        head, *tail = pts
        parts = [f"M {head[0]:.1f} {head[1]:.1f}"]
        parts.extend(f"L {x:.1f} {y:.1f}" for x, y in tail)
        return " ".join(parts)

    restriction_nodes = []
    for tr in restrictions_doc.get("turn_restrictions", []):
        if isinstance(tr, dict):
            node_id = tr.get("junction_node_id")
            if isinstance(node_id, str) and node_id in nodes:
                restriction_nodes.append(
                    (node_id, tr.get("restriction", "restriction"), nodes[node_id])
                )

    route_props = {}
    for feature in route_doc.get("features", []):
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict):
            if feature["properties"].get("kind") == "route":
                route_props = feature["properties"]
                break
    total_length = float(route_props.get("total_length_m", 0.0) or 0.0)
    edge_count = int(route_props.get("edge_count", len(route_lines)) or len(route_lines))
    reachable_props = reachable_doc.get("properties", {})
    if not isinstance(reachable_props, dict):
        reachable_props = {}
    reachable_budget = float(reachable_props.get("max_cost_m", 0.0) or 0.0)
    reachable_nodes = int(reachable_props.get("node_count", 0) or 0)
    reachable_edges = int(reachable_props.get("edge_count", len(reachable_lines)) or len(reachable_lines))

    svg: list[str] = []
    svg.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {int(width)} {int(height)}" '
        'role="img" aria-labelledby="title desc">'
    )
    svg.append("<title id=\"title\">Paris OSM-highway grid route and reachability preview</title>")
    svg.append(
        "<desc id=\"desc\">Static preview of a route and reachable service area across a Paris road graph "
        "with turn-restriction junctions highlighted.</desc>"
    )
    svg.append("<rect width=\"1200\" height=\"720\" fill=\"#f8fafc\"/>")
    svg.append(
        "<rect x=\"32\" y=\"32\" width=\"1136\" height=\"656\" rx=\"18\" "
        "fill=\"#ffffff\" stroke=\"#d9e2ec\"/>"
    )
    svg.append("<g opacity=\"0.36\">")
    for x in range(80, 880, 80):
        svg.append(f'<path d="M {x} 58 L {x} 650" stroke="#e2e8f0" stroke-width="1"/>')
    for y in range(80, 660, 80):
        svg.append(f'<path d="M 58 {y} L 882 {y}" stroke="#e2e8f0" stroke-width="1"/>')
    svg.append("</g>")
    svg.append("<g fill=\"none\" stroke-linecap=\"round\" stroke-linejoin=\"round\">")
    for line in centerlines:
        svg.append(
            f'<path d="{path_d(line)}" stroke="#94a3b8" stroke-width="1.55" '
            'opacity="0.58"/>'
        )
    svg.append("</g>")
    svg.append("<g fill=\"none\" stroke-linecap=\"round\" stroke-linejoin=\"round\">")
    for line, complete in reachable_lines:
        dash = "" if complete else ' stroke-dasharray="7 7"'
        opacity = "0.42" if complete else "0.50"
        svg.append(
            f'<path d="{path_d(line)}" stroke="#0f766e" stroke-width="6.0" '
            f'opacity="{opacity}"{dash}/>'
        )
    svg.append("</g>")
    svg.append("<g fill=\"none\" stroke-linecap=\"round\" stroke-linejoin=\"round\">")
    for line in route_lines:
        svg.append(f'<path d="{path_d(line)}" stroke="#0f172a" stroke-width="9.0" opacity="0.26"/>')
    if route_main:
        svg.append(
            f'<path d="{path_d(route_main)}" stroke="#0f172a" stroke-width="11.0" '
            'opacity="0.24"/>'
        )
        svg.append(f'<path d="{path_d(route_main)}" stroke="#2563eb" stroke-width="5.2"/>')
    for line in route_lines:
        svg.append(f'<path d="{path_d(line)}" stroke="#60a5fa" stroke-width="3.2"/>')
    svg.append("</g>")
    svg.append("<g>")
    for _, restriction, pt in restriction_nodes:
        x, y = project(pt)
        label = html.escape(str(restriction))
        svg.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.0" fill="#dc2626" '
            f'stroke="#ffffff" stroke-width="1.6"><title>{label}</title></circle>'
        )
    svg.append("</g>")
    if reachable_start is not None:
        x, y = project(reachable_start)
        svg.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="10.0" fill="#0f766e" '
            f'stroke="#ffffff" stroke-width="2.3"><title>reachable start</title></circle>'
        )
    for cls, pt, fill in (("Start", start_pt, "#16a34a"), ("End", end_pt, "#ef4444")):
        if pt is None:
            continue
        x, y = project(pt)
        svg.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8.5" fill="{fill}" '
            f'stroke="#ffffff" stroke-width="2.2"><title>{cls}</title></circle>'
        )

    panel_x, panel_y = 892, 70
    svg.append(f'<g transform="translate({panel_x} {panel_y})">')
    svg.append(
        '<text x="0" y="0" font-family="Inter, ui-sans-serif, system-ui, sans-serif" '
        'font-size="16" font-weight="700" fill="#0f172a">Paris route + reachability</text>'
    )
    svg.append(
        '<text x="0" y="26" font-family="Inter, ui-sans-serif, system-ui, sans-serif" '
        'font-size="12" fill="#475569">OSM-highway graph + TR-aware Dijkstra</text>'
    )
    stats = [
        ("graph edges", str(len(centerlines))),
        ("graph nodes", str(len(nodes))),
        ("OSM restrictions", str(len(restriction_nodes))),
        ("reachable budget", f"{reachable_budget:.0f} m"),
        ("reachable nodes", str(reachable_nodes)),
        ("reachable spans", str(reachable_edges)),
        ("route length", f"{total_length:.0f} m"),
        ("route edges", str(edge_count)),
    ]
    y = 68
    for label, value in stats:
        svg.append(
            f'<text x="0" y="{y}" font-family="Inter, ui-sans-serif, system-ui, sans-serif" '
            f'font-size="11" fill="#64748b">{html.escape(label)}</text>'
        )
        svg.append(
            f'<text x="160" y="{y}" text-anchor="end" '
            'font-family="Inter, ui-sans-serif, system-ui, sans-serif" '
            f'font-size="15" font-weight="700" fill="#0f172a">{html.escape(value)}</text>'
        )
        svg.append(f'<path d="M 0 {y + 12} L 170 {y + 12}" stroke="#e2e8f0" stroke-width="1"/>')
        y += 42
    svg.append(
        '<g transform="translate(0 430)" '
        'font-family="Inter, ui-sans-serif, system-ui, sans-serif" '
        'font-size="12" fill="#475569">'
    )
    svg.append(
        '<circle cx="6" cy="-4" r="5" fill="#dc2626"/>'
        '<text x="20" y="0">turn-restriction junction</text>'
    )
    svg.append(
        '<path d="M 0 24 L 38 24" stroke="#2563eb" stroke-width="5" '
        'stroke-linecap="round"/><text x="50" y="28">selected route</text>'
    )
    svg.append(
        '<path d="M 0 54 L 38 54" stroke="#0f766e" stroke-width="5" '
        'stroke-linecap="round" opacity="0.55"/>'
        '<text x="50" y="58">500 m reachable span</text>'
    )
    svg.append(
        '<path d="M 0 84 L 38 84" stroke="#94a3b8" stroke-width="2" '
        'stroke-linecap="round" opacity="0.7"/>'
        '<text x="50" y="88">road graph centerline</text>'
    )
    svg.append("</g>")
    svg.append("</g>")
    svg.append(
        '<text x="70" y="668" font-family="Inter, ui-sans-serif, system-ui, sans-serif" '
        'font-size="11" fill="#64748b">Derived from OpenStreetMap data '
        "© OpenStreetMap contributors, ODbL-1.0. Static preview generated from "
        "docs/assets.</text>"
    )
    svg.append("</svg>")
    (IMAGES / "paris_grid_route.svg").write_text("\n".join(svg) + "\n", encoding="utf-8")


def main() -> None:
    from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
    from roadgraph_builder.io.camera.detections import apply_camera_detections_to_graph, load_camera_detections_json
    from roadgraph_builder.io.export.geojson import export_map_geojson
    from roadgraph_builder.io.export.json_exporter import export_graph_json
    from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
    from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
    from roadgraph_builder.viz.svg_export import write_trajectory_graph_svg

    ASSETS.mkdir(parents=True, exist_ok=True)
    IMAGES.mkdir(parents=True, exist_ok=True)

    # Toy sample
    toy_csv = ROOT / "examples" / "sample_trajectory.csv"
    toy_origin = ROOT / "examples" / "toy_map_origin.json"
    shutil.copyfile(toy_csv, ASSETS / "sample_trajectory.csv")
    shutil.copyfile(toy_origin, ASSETS / "toy_map_origin.json")
    toy_traj = load_trajectory_csv(toy_csv)
    toy_graph = build_graph_from_trajectory(toy_traj, BuildParams())
    enrich_sd_to_hd(toy_graph, SDToHDConfig(lane_width_m=3.5))
    det_json = ROOT / "examples" / "camera_detections_sample.json"
    if det_json.is_file():
        apply_camera_detections_to_graph(toy_graph, load_camera_detections_json(det_json))
    export_graph_json(toy_graph, ASSETS / "sample_graph.json")
    write_trajectory_graph_svg(toy_traj, toy_graph, IMAGES / "sample_trajectory.svg", width=960, height=640)
    tlat, tlon = _load_origin(toy_origin)
    export_map_geojson(
        toy_graph,
        toy_traj.xy,
        ASSETS / "map_toy.geojson",
        origin_lat=tlat,
        origin_lon=tlon,
        dataset_name="toy",
    )

    # OSM sample (same params as README)
    osm_csv = ROOT / "examples" / "osm_public_trackpoints.csv"
    osm_origin_file = ROOT / "examples" / "osm_public_trackpoints_origin.json"
    shutil.copyfile(osm_csv, ASSETS / "osm_trajectory.csv")
    if (ROOT / "examples" / "osm_public_trackpoints_wgs84.csv").is_file():
        shutil.copyfile(ROOT / "examples" / "osm_public_trackpoints_wgs84.csv", ASSETS / "osm_wgs84.csv")
    shutil.copyfile(osm_origin_file, ASSETS / "osm_origin.json")
    osm_traj = load_trajectory_csv(osm_csv)
    p = BuildParams(max_step_m=40.0, merge_endpoint_m=12.0, centerline_bins=32)
    osm_graph = build_graph_from_trajectory(osm_traj, p)
    enrich_sd_to_hd(osm_graph, SDToHDConfig(lane_width_m=3.5))
    if det_json.is_file():
        apply_camera_detections_to_graph(osm_graph, load_camera_detections_json(det_json))
    export_graph_json(osm_graph, ASSETS / "osm_graph.json")
    write_trajectory_graph_svg(osm_traj, osm_graph, IMAGES / "osm_public.svg", width=960, height=640)
    olat, olon = _load_origin(osm_origin_file)
    export_map_geojson(
        osm_graph,
        osm_traj.xy,
        ASSETS / "map_osm.geojson",
        origin_lat=olat,
        origin_lon=olon,
        dataset_name="osm",
        attribution="© OpenStreetMap contributors",
        license_name="ODbL-1.0",
        license_url="https://opendatacommons.org/licenses/odbl/1-0/",
    )

    # OSM-highway-derived Paris grid + turn_restrictions demo
    # Fetch + convert are left to the user (requires network access); this
    # block only regenerates the three committed artefacts when the inputs
    # already exist under /tmp.
    paris_highways = Path("/tmp/osm_real_data/paris_highways.json")
    paris_tr_raw = Path("/tmp/osm_real_data/paris_turn_restrictions_raw.json")
    paris_origin = ROOT / "examples" / "toy_map_origin.json"  # fallback label
    paris_origin_json = Path("/tmp/osm_real_data/paris_merged_origin.json")
    if paris_highways.is_file() and paris_tr_raw.is_file() and paris_origin_json.is_file():
        from roadgraph_builder.io.osm import (
            build_graph_from_overpass_highways,
            convert_osm_restrictions_to_graph,
            load_overpass_json,
        )
        from roadgraph_builder.io.osm.turn_restrictions import strip_private_fields
        from roadgraph_builder.navigation.turn_restrictions import load_turn_restrictions_json
        from roadgraph_builder.pipeline.build_graph import BuildParams
        from roadgraph_builder.routing.geojson_export import write_route_geojson
        from roadgraph_builder.routing.shortest_path import shortest_path
        import numpy as np

        lat0, lon0 = _load_origin(paris_origin_json)
        hovp = load_overpass_json(paris_highways)
        grid = build_graph_from_overpass_highways(
            hovp,
            origin_lat=lat0,
            origin_lon=lon0,
            params=BuildParams(
                simplify_tolerance_m=0.0,
                post_simplify_tolerance_m=0.0,
                merge_endpoint_m=2.0,
            ),
        )
        # Stamp OSM highway / lanes / maxspeed / oneway / name tags onto the
        # graph edge attributes so every downstream export (GeoJSON for the
        # viewer, Lanelet2 OSM for Autoware) picks them up.
        paris_way_specs = _collect_osm_way_polylines(
            hovp, lat0, lon0, _OSM_WANTED_HIGHWAYS
        )
        _inject_osm_tags_into_graph_edges(grid, lat0, lon0, paris_way_specs)
        # Apply precomputed SRTM-30m elevations (via Open-Elevation) if
        # available, so every graph node carries `elevation_m` and every edge
        # carries a `polyline_z` list. This is what turns `build --3d` and
        # `route --uphill-penalty` / `--downhill-bonus` into meaningful
        # operations for this committed dataset.
        paris_elev_path = Path("/tmp/osm_real_data/paris_node_elevations.json")
        if paris_elev_path.is_file():
            elev_doc = json.loads(paris_elev_path.read_text(encoding="utf-8"))
            elevs = elev_doc.get("elevations") or {}
            if isinstance(elevs, dict):
                _apply_node_elevations(grid, elevs)
        # Populate HD-lite lane boundaries so the viewer can render the green /
        # purple dashed lines. Without this the 3D / 2D views only show the
        # orange centerlines for the Paris grid.
        enrich_sd_to_hd(grid, SDToHDConfig(lane_width_m=3.5))
        # Multi-lane OSM roads (``lanes>=2``) need a wider envelope than the
        # default single-lane 3.5 m offset; recompute lane_boundaries for them
        # so the paint lines hug the true road width.
        _widen_hd_envelope_for_osm_lanes(grid, base_lane_width_m=3.5)
        # Prefer real OSM regulatory nodes (traffic_signals / stop / crossing /
        # give_way / speed_camera) projected onto the nearest graph edge. The
        # upstream fetch is ``scripts/fetch_osm_regulatory_nodes.py``; we use
        # its cached output under /tmp when present. When absent we fall back
        # to the hand-authored synthetic sample so the committed dataset
        # still carries some regulatory markers.
        paris_regulatory_osm_path = Path(
            "/tmp/osm_real_data/paris_regulatory_nodes.json"
        )
        paris_camera_json = ASSETS / "paris_grid_camera_detections.json"
        paris_camera_observations: list[dict] = []
        from roadgraph_builder.io.camera.detections import (
            apply_camera_detections_to_graph,
        )
        if paris_regulatory_osm_path.is_file():
            overpass_reg = json.loads(
                paris_regulatory_osm_path.read_text(encoding="utf-8")
            )
            paris_camera_observations = _osm_regulatory_observations(
                overpass_reg, grid, lat0, lon0, max_crossings=160
            )
            if paris_camera_observations:
                apply_camera_detections_to_graph(grid, paris_camera_observations)
                # Overwrite the committed sample with the OSM-derived one so
                # downstream consumers (documentation, CI, future snapshots)
                # see the real regulatory data rather than the synthetic demo.
                paris_camera_json.write_text(
                    json.dumps(
                        {
                            "format_version": 1,
                            "license": (
                                "© OpenStreetMap contributors, ODbL 1.0 "
                                "(derived from Overpass regulatory nodes)"
                            ),
                            "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
                            "notes": (
                                "Edge-keyed projections of OSM "
                                "highway=traffic_signals / stop / crossing / "
                                "give_way / speed_camera nodes onto the "
                                "committed Paris grid via nearest "
                                "point-to-polyline match."
                            ),
                            "observations": paris_camera_observations,
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
        elif paris_camera_json.is_file():
            paris_camera_raw = json.loads(paris_camera_json.read_text(encoding="utf-8"))
            paris_camera_observations = [
                o for o in (paris_camera_raw.get("observations") or [])
                if isinstance(o, dict) and o.get("edge_id") and o.get("kind")
            ]
            if paris_camera_observations:
                apply_camera_detections_to_graph(grid, paris_camera_observations)
        # Infer a per-edge lane count (defaults to 1 lane when no lane_markings
        # or trace_stats are available — which is the Paris-grid case) and
        # emit a committed per-lane Lanelet2 OSM so the docs can demonstrate
        # Autoware-compatible output without a CLI run.
        try:
            from roadgraph_builder.cli.hd import apply_lane_inferences
            from roadgraph_builder.hd.lane_inference import infer_lane_counts
            from roadgraph_builder.io.export.lanelet2 import (
                export_lanelet2_per_lane,
            )

            inferences = infer_lane_counts(
                grid.to_dict(),
                base_lane_width_m=3.5,
            )
            apply_lane_inferences(grid, inferences)
            # Intentionally do NOT re-apply camera detections here: an earlier
            # call already stamped them into `edge.attributes.hd.semantic_rules`,
            # and `apply_lane_inferences` preserves existing hd entries. A
            # second apply would double the rule list and inflate the regulatory
            # element count emitted below.
            paris_lanelet_path = ASSETS / "map_paris_grid.lanelet.osm"
            export_lanelet2_per_lane(
                grid,
                paris_lanelet_path,
                origin_lat=lat0,
                origin_lon=lon0,
            )
        except Exception as exc:  # pragma: no cover - best-effort docs refresh
            print(f"paris_grid Lanelet2 export skipped: {exc}")
        tr_raw = load_overpass_json(paris_tr_raw)
        conv = convert_osm_restrictions_to_graph(grid, tr_raw, max_snap_distance_m=15.0)
        cleaned = strip_private_fields(conv.restrictions)
        (ASSETS / "paris_grid_turn_restrictions.json").write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "attribution": "© OpenStreetMap contributors",
                    "license": "ODbL-1.0",
                    "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
                    "turn_restrictions": cleaned,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        grid_geo_tmp = ASSETS / "_map_paris_grid.tmp.geojson"
        export_map_geojson(
            grid,
            np.zeros((0, 2)),
            grid_geo_tmp,
            origin_lat=lat0,
            origin_lon=lon0,
            dataset_name="paris_grid",
            attribution="© OpenStreetMap contributors",
            license_name="ODbL-1.0",
            license_url="https://opendatacommons.org/licenses/odbl/1-0/",
        )
        raw = json.loads(grid_geo_tmp.read_text(encoding="utf-8"))
        for f in raw["features"]:
            p = f["properties"]
            for k in ("source", "direction_observed"):
                p.pop(k, None)
        # The OSM highway / lanes / maxspeed / oneway / name tags are already
        # on every edge.attributes from the earlier graph-level stamp, so
        # export_map_geojson has already spread them into the feature
        # properties via **e.attributes. No GeoJSON-level re-injection needed.
        if paris_camera_observations:
            _append_semantic_overlay_points(
                raw, paris_camera_observations, "paris_grid"
            )
        (ASSETS / "map_paris_grid.geojson").write_text(
            json.dumps(raw, separators=(",", ":")), encoding="utf-8"
        )
        grid_geo_tmp.unlink(missing_ok=True)
        trs = load_turn_restrictions_json(ASSETS / "paris_grid_turn_restrictions.json")
        route = shortest_path(
            grid,
            PARIS_GRID_ROUTE_FROM_NODE,
            PARIS_GRID_ROUTE_TO_NODE,
            turn_restrictions=trs,
        )
        write_route_geojson(
            ASSETS / "route_paris_grid.geojson",
            grid,
            route,
            origin_lat=lat0,
            origin_lon=lon0,
            attribution="© OpenStreetMap contributors",
            license_name="ODbL-1.0",
            license_url="https://opendatacommons.org/licenses/odbl/1-0/",
        )

    # OSM-highway-derived Berlin Mitte HD-lite sample
    # Same inputs shape as the Paris grid block; shipped so the committed
    # viewer can switch between European and (future) Asian demos without a
    # live Overpass fetch. Leaves turn restrictions unshipped for now — add
    # later when the raw relation dump is available.
    berlin_raw = Path("/tmp/berlin_mitte_raw.json")
    if berlin_raw.is_file():
        from roadgraph_builder.io.osm import (
            build_graph_from_overpass_highways,
            load_overpass_json,
        )
        from roadgraph_builder.pipeline.build_graph import BuildParams
        import numpy as np

        # Berlin Mitte bbox roughly lat 52.506–52.526, lon 13.367–13.401.
        berlin_origin = {"latitude": 52.5160, "longitude": 13.3840}
        (ASSETS / "berlin_mitte_origin.json").write_text(
            json.dumps(berlin_origin, indent=2) + "\n", encoding="utf-8"
        )
        hovp = load_overpass_json(berlin_raw)
        berlin_graph = build_graph_from_overpass_highways(
            hovp,
            origin_lat=berlin_origin["latitude"],
            origin_lon=berlin_origin["longitude"],
            params=BuildParams(
                simplify_tolerance_m=0.0,
                post_simplify_tolerance_m=0.0,
                merge_endpoint_m=2.0,
            ),
        )
        berlin_way_specs = _collect_osm_way_polylines(
            hovp,
            berlin_origin["latitude"],
            berlin_origin["longitude"],
            _OSM_WANTED_HIGHWAYS,
        )
        _inject_osm_tags_into_graph_edges(
            berlin_graph,
            berlin_origin["latitude"],
            berlin_origin["longitude"],
            berlin_way_specs,
        )
        berlin_elev_path = Path("/tmp/osm_real_data/berlin_node_elevations.json")
        if berlin_elev_path.is_file():
            elev_doc = json.loads(berlin_elev_path.read_text(encoding="utf-8"))
            elevs = elev_doc.get("elevations") or {}
            if isinstance(elevs, dict):
                _apply_node_elevations(berlin_graph, elevs)
        enrich_sd_to_hd(berlin_graph, SDToHDConfig(lane_width_m=3.5))
        _widen_hd_envelope_for_osm_lanes(berlin_graph, base_lane_width_m=3.5)
        berlin_geo_tmp = ASSETS / "_map_berlin_mitte.tmp.geojson"
        export_map_geojson(
            berlin_graph,
            np.zeros((0, 2)),
            berlin_geo_tmp,
            origin_lat=berlin_origin["latitude"],
            origin_lon=berlin_origin["longitude"],
            dataset_name="berlin_mitte",
            attribution="© OpenStreetMap contributors",
            license_name="ODbL-1.0",
            license_url="https://opendatacommons.org/licenses/odbl/1-0/",
        )
        raw = json.loads(berlin_geo_tmp.read_text(encoding="utf-8"))
        for f in raw["features"]:
            pp = f["properties"]
            for k in ("source", "direction_observed"):
                pp.pop(k, None)
        (ASSETS / "map_berlin_mitte.geojson").write_text(
            json.dumps(raw, separators=(",", ":")), encoding="utf-8"
        )
        berlin_geo_tmp.unlink(missing_ok=True)
        try:
            from roadgraph_builder.cli.hd import apply_lane_inferences
            from roadgraph_builder.hd.lane_inference import infer_lane_counts
            from roadgraph_builder.io.export.lanelet2 import (
                export_lanelet2_per_lane,
            )

            berlin_inferences = infer_lane_counts(
                berlin_graph.to_dict(),
                base_lane_width_m=3.5,
            )
            apply_lane_inferences(berlin_graph, berlin_inferences)
            export_lanelet2_per_lane(
                berlin_graph,
                ASSETS / "map_berlin_mitte.lanelet.osm",
                origin_lat=berlin_origin["latitude"],
                origin_lon=berlin_origin["longitude"],
            )
        except Exception as exc:  # pragma: no cover - best-effort docs refresh
            print(f"berlin_mitte Lanelet2 export skipped: {exc}")

    _write_paris_grid_reachability_asset()
    _write_route_explain_sample_asset()
    _write_map_match_explain_sample_asset()

    # Viewer metadata (bounds hint optional)
    meta = {
        "datasets": [
            {"id": "toy", "label": "Toy trajectory", "graph": "assets/sample_graph.json", "csv": "assets/sample_trajectory.csv"},
            {"id": "osm", "label": "OSM public GPS (Berlin area sample)", "graph": "assets/osm_graph.json", "csv": "assets/osm_trajectory.csv"},
        ]
    }
    (ASSETS / "viewer_config.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    repo_url = os.environ.get("ROADGRAPH_REPO_URL", DEFAULT_REPO_URL).rstrip("/")
    pages_url = os.environ.get("ROADGRAPH_PAGES_URL", DEFAULT_PAGES_URL).rstrip("/") + "/"
    site = {"repository_url": repo_url + "/", "pages_url": pages_url, "map_url": pages_url + "map.html"}
    (ASSETS / "site.json").write_text(json.dumps(site, indent=2) + "\n", encoding="utf-8")
    _render_paris_grid_route_preview()
    print("Wrote docs/assets and docs/images")


if __name__ == "__main__":
    main()
