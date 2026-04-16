# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Distribution** — `scripts/build_release_bundle.sh` + `.github/workflows/release.yml` attach a validated `roadgraph_sample_bundle.tar.gz` (plus sha256) to every `v*` tag; a trimmed `examples/frozen_bundle/` is committed for quick inspection. `make release-bundle` wraps the script.
- **Navigation restrictions (generator)** — `export-bundle --turn-restrictions-json` plus extraction from camera detections (`kind: turn_restriction`) now populate `sd_nav.turn_restrictions`; new `validate-turn-restrictions` CLI + schema.
- **Guard rails** — `build` / `visualize` / `export-bundle` fail with a clear message when the trajectory yields **no graph edges** (e.g. too few samples per segment), instead of writing an unusable empty graph.
- **CLI errors** — Missing input JSON/CSV files print `File not found: …` and exit 1; schema validation errors are prefixed with the file path.
- **Navigation + HD** — `nav/sd_nav.json` `allowed_maneuvers` inferred at the digitized **end node** from 2D junction geometry (`topology_geometry_v1`); `metadata.sd_to_hd.navigation_hints` points consumers at `sd_nav` and describes pairing with HD lane boundaries.
- **Navigation restrictions schema** — optional `sd_nav.turn_restrictions` validates directed edge transition restrictions separately from geometry-derived maneuver hints.
- **Bundle tuning** — `docs/bundle_tuning.md` and `scripts/run_tuning_bundle.sh`; `make tune` runs a minimal `export-bundle` + validation for exploring `max-step-m` / `merge-endpoint-m` with `sim/map.geojson`.
- **Planning / handoff** — `docs/PLAN.md` for roadmap, facts vs intent, and Codex continuation checklist (linked from README).
- **SD→HD envelope** — `enrich_sd_to_hd()` + CLI `enrich`: optional `metadata.sd_to_hd`, per-edge/node `attributes.hd` placeholders (empty lane boundaries); `load_graph_json()`; optional document `metadata` on `Graph`.
- **HD-lite boundaries** — `enrich --lane-width-m` + `centerline_lane_boundaries()`: offset left/right polylines from edge centerlines (not LiDAR/survey-grade).
- **Map GeoJSON** — `build_map_geojson()` emits `lane_boundary_left` / `lane_boundary_right` LineStrings; `docs/map.html` styles them; `refresh_docs_assets.py` runs HD-lite enrich (3.5 m) before exporting bundled maps.
- **Map legend** — `docs/map.html` bottom-right Leaflet control explains trajectory / centerline / lane L&R / nodes.
- **LiDAR (minimal)** — `load_points_xy_csv()`, `attach_lidar_points_metadata()`; sample `examples/sample_lidar_points.csv`. LAS/LAZ still `NotImplementedError`.
- **LiDAR fusion** — `fuse_lane_boundaries_from_points()` + CLI `fuse-lidar`: proximity to centerline, left/right via cross product, binned median polylines per edge.
- **OSM / Lanelet2 interchange** — `export_lanelet2()` writes OSM XML 0.6 (nodes, ways, `roadgraph:*` tags); CLI `export-lanelet2` with `--origin-lat`/`--lon` or `metadata.map_origin`.
- **Lanelet relations** — when both lane boundary ways exist, emit `type=lanelet` with `left`/`right` (+ optional `centerline`) members.
- **Camera semantics (JSON)** — `load_camera_detections_json` / `apply_camera_detections_to_graph`, CLI `apply-camera`; `export_lanelet2` adds `speed_limit` and `regulatory_element` from `hd.semantic_rules`.
- **Detections schema** — `camera_detections.schema.json`, `validate_camera_detections_document`, CLI `validate-detections`; GeoJSON `semantic_summary` on centerlines; `refresh_docs_assets.py` runs sample `apply-camera`; map popups show `semantic_summary`.
- **Road graph schema** — `road_graph.schema.json` documents optional `attributes.hd` (`lane_boundaries`, `semantic_rules` with required `kind`); CI runs `validate-detections` on the bundled example.
- **CI** — `validate` on `docs/assets/sample_graph.json` and `docs/assets/osm_graph.json` (Pages-bundled graphs).
- **export-bundle** — `export_map_bundle()` + CLI: `nav/sd_nav.json`, `sim/{road_graph,map,trajectory}`, `lanelet/map.osm` in one directory (SD / sim / Lanelet three-way export).
- **sd_nav schema** — `sd_nav.schema.json`, `validate_sd_nav_document`, CLI `validate-sd-nav`; CI runs `export-bundle` + `validate-sd-nav` on the sample trajectory.
- **Bundle manifest + CI** — `export-bundle` writes `manifest.json` (version, UTC time, origin, inputs); CI also `validate`s `sim/road_graph.json` from the bundle.
- **Manifest schema** — `manifest.schema.json`, `validate_manifest_document`, CLI `validate-manifest`; CI and `run_demo_bundle.sh` validate `manifest.json` after bundle export.
- **Practical UX** — `export-bundle --origin-json` (lat0/lon0 file); `load_wgs84_origin_json`; `scripts/run_demo_bundle.sh`; manifest records `origin_source` / `origin_json` basename.
- **Developer ergonomics** — CLI `doctor`; `Makefile` (`make install|test|demo|doctor`); `sd_nav` edges include `allowed_maneuvers` (default `["straight"]`; schema allows future routing values).
- **Douglas–Peucker** polyline simplification (`BuildParams.simplify_tolerance_m`, CLI `--simplify-tolerance`).
- **Node topology attributes:** `degree` and `junction_hint` (dead-end / through / multi-branch) via `annotate_node_degrees()`.
- **`Node.attributes`** on export (optional in JSON schema).
- **GeoJSON + Leaflet** — `docs/map.html` overlays trajectory / centerlines / nodes on **OpenStreetMap** tiles; `export_map_geojson()` and `utils/geo.py` (meters ↔ WGS84).
- **OSM fetch** — writes `*_origin.json` and `*_wgs84.csv` next to the meters CSV.

### Changed

- **Navigation maneuvers** — T/Y junction hints stay permissive when sparse geometry shows a straight continuation plus only one side branch, avoiding accidental one-sided turn restrictions in `sd_nav`.
- **`visualize` SVG** — map-inspired styling (grid, trajectory polyline, road-width stroke under centerline, scale bar, refreshed `docs/images` for README).

### Documentation

- **Navigation restrictions:** documented that `allowed_maneuvers` is a permissive geometry hint, plus a future `turn_restrictions` extension shape.
- **README:** SD map vs HD map table (how this repo relates to each).

## [0.2.0] — 2026-04-15

### Added

- **`docs/`** static site: interactive pan/zoom viewer for graph JSON + trajectory CSV (GitHub Pages–ready).
- **`scripts/refresh_docs_assets.py`** — rebuild `docs/assets` and README preview SVGs from `examples/`.
- **README** preview images under `docs/images/` (toy + OSM samples).

### Changed

- **`visualize` SVG** — gradient background and soft glow on centerlines.

## [0.1.0] — 2026-04-15

### Added

- Graph-first JSON export (`schema_version`, nodes, edges with centerline polylines).
- CLI: `build`, `visualize` (SVG), `validate` (JSON Schema).
- Trajectory CSV loader and MVP pipeline (gap segmentation, PCA centerline, endpoint merge).
- OSM public GPS sample (`examples/osm_public_trackpoints.csv`) and fetch script.
- Tests and CI (Python 3.10 / 3.12).
- Stubs: LiDAR, camera, Lanelet2 export.

[0.2.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.2.0
[0.1.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.1.0
