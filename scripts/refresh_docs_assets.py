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


def _load_origin(path: Path) -> tuple[float, float]:
    d = json.loads(path.read_text(encoding="utf-8"))
    return float(d["lat0"]), float(d["lon0"])


def _render_paris_grid_route_preview() -> None:
    """Render a static SVG preview for README / GitHub Pages."""
    map_path = ASSETS / "map_paris_grid.geojson"
    route_path = ASSETS / "route_paris_grid.geojson"
    restrictions_path = ASSETS / "paris_grid_turn_restrictions.json"
    if not (map_path.is_file() and route_path.is_file() and restrictions_path.is_file()):
        return

    map_doc = json.loads(map_path.read_text(encoding="utf-8"))
    route_doc = json.loads(route_path.read_text(encoding="utf-8"))
    restrictions_doc = json.loads(restrictions_path.read_text(encoding="utf-8"))

    centerlines: list[list[tuple[float, float]]] = []
    nodes: dict[str, tuple[float, float]] = {}
    route_lines: list[list[tuple[float, float]]] = []
    route_main: list[tuple[float, float]] = []
    start_pt: tuple[float, float] | None = None
    end_pt: tuple[float, float] | None = None

    def _coords(line: object) -> list[tuple[float, float]]:
        if not isinstance(line, list):
            return []
        out: list[tuple[float, float]] = []
        for pt in line:
            if isinstance(pt, list) and len(pt) >= 2:
                out.append((float(pt[0]), float(pt[1])))
        return out

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

    svg: list[str] = []
    svg.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {int(width)} {int(height)}" '
        'role="img" aria-labelledby="title desc">'
    )
    svg.append("<title id=\"title\">Paris OSM-highway grid route preview</title>")
    svg.append(
        "<desc id=\"desc\">Static preview of a route across a Paris road graph "
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
        'font-size="16" font-weight="700" fill="#0f172a">Paris grid route</text>'
    )
    svg.append(
        '<text x="0" y="26" font-family="Inter, ui-sans-serif, system-ui, sans-serif" '
        'font-size="12" fill="#475569">OSM-highway graph + TR-aware Dijkstra</text>'
    )
    stats = [
        ("graph edges", str(len(centerlines))),
        ("graph nodes", str(len(nodes))),
        ("OSM restrictions", str(len(restriction_nodes))),
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
        '<g transform="translate(0 308)" '
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
        '<path d="M 0 54 L 38 54" stroke="#94a3b8" stroke-width="2" '
        'stroke-linecap="round" opacity="0.7"/>'
        '<text x="50" y="58">road graph centerline</text>'
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
        (ASSETS / "map_paris_grid.geojson").write_text(
            json.dumps(raw, separators=(",", ":")), encoding="utf-8"
        )
        grid_geo_tmp.unlink(missing_ok=True)
        trs = load_turn_restrictions_json(ASSETS / "paris_grid_turn_restrictions.json")
        route = shortest_path(grid, "n312", "n191", turn_restrictions=trs)
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
