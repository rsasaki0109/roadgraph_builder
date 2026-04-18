# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Junction cluster consolidation** — new `consolidate_clustered_junctions` pass runs at the end of `polylines_to_graph`. It finds pairs of `multi_branch` nodes within `1.75 × merge_endpoint_m` of each other, union-finds them into a single cluster, collapses each cluster to one node at the centroid, and rewrites incident edges. Cleans up the case where one real intersection is split across two or three anchor points because different polylines reached the junction from slightly different directions. Paris: 1 node absorbed (conservative tolerance keeps the effect small).
- **Near-parallel edge merge** — new `merge_near_parallel_edges` pass runs after the exact-duplicate merge. For every pair of edges whose endpoint-to-endpoint distance sum is below `2 * merge_endpoint_m` (both forward and reversed pairings are considered), the corresponding node ids are union-found into a single cluster. Each cluster collapses to one node at the cluster's centroid, edges are rewritten, and the follow-up duplicate merge averages what are now identical endpoint pairs. Paris OSM: edges 247 → 242, nodes 254 → 250, LCC unchanged at 53 %. Catches the "same road walked twice, each pass anchoring to a slightly different junction cluster" case that exact-duplicate folding missed.
- **Duplicate edge merge** — `polylines_to_graph` now folds edges that share the same (start, end) node pair (regardless of direction) into a single edge. Each polyline is resampled at `centerline_bins` arc-length-uniform samples, reversed when walked in the opposite canonical direction, and per-sample averaged. The merged edge stores `attributes.merged_edge_count`, so downstream consumers can see "this centerline is the average of N passes". On the Paris OSM trace: edges 347 → **247** (100 redundant passes absorbed into 71 averaged centerlines). The largest connected component is unchanged (135 / 53 %); previously-phantom `multi_branch` nodes that were only branching via duplicates collapse back to `through_or_corner`, so the node classification distribution is more honest (`multi_branch` 112 → 67).
- **Miter-joined lane offsets** — `centerline_lane_boundaries` replaces the previous central-difference unit-normal offset with a proper miter join: interior vertices sit on the angle bisector of the two adjacent edge normals at the miter length that keeps perpendicular distance to each incident infinite edge-line equal to the configured half-width. Near-180° reversals fall back to a bevel (two separate offset vertices) once the miter would exceed `miter_limit * half_width`. The old code kept the ribbon a roughly constant chord-distance from the centerline, which under-offset on the inside of sharp curves and flared on the outside; the new version behaves correctly on straight, 90°, and hairpin samples. No public API break; `centerline_lane_boundaries(polyline, lane_width_m)` still returns `(left, right)` polylines, optionally with `miter_limit=4.0` for custom join clamping.
- **X-junction splitting in `build`** — `polylines_to_graph` now runs `split_polylines_at_crossings` before the T-junction / union-find passes. Every pair of polylines whose interiors strictly cross is cut at the intersection, so crossings become real junction nodes instead of phantom unrelated edges. Bounding-box pre-filter keeps the pair scan tractable. On the Paris OSM trace the accumulated splitting (X + T + endpoint merge) now yields 347 edges / 254 nodes, a **135-node largest connected component (53 % of the graph)**, and correct labelling of 18 `x_junction` + 8 `crossroads` nodes that used to collapse into `complex_junction`. The viewer now draws a 19-edge 1923 m Dijkstra route across the LCC.
- **T-junction splitting in `build`** — `polylines_to_graph` now calls a new `split_polylines_at_t_junctions` pass before endpoint union-find: whenever one polyline's endpoint lands within `merge_endpoint_m` of another polyline's *interior* (not its own endpoint), the target polyline is split at the projection so both sides share a junction vertex the union-find can fuse. Guarded by `min_interior_m=1.0` so we don't double-split at tip-to-tip cases the old endpoint-merge already handles. Paris OSM result (`--max-step-m 40 --merge-endpoint-m 8`): edges 123 → 221, largest connected component 5 → **84 nodes** (40 % of the graph), `multi_branch` nodes 3 → 72 (12 `t_junction` + 37 `y_junction` + 23 `complex_junction`). The viewer now draws a 3 km 6-edge route along the connected component; before, no path longer than ~1 km existed.
- **Centerline smoothing upgrade** — `centerline_from_points` now walks the time-ordered segment, computes cumulative arc length, and resamples at ``num_bins`` positions using a Gaussian window in arc-length space (raw first/last points are anchored so the endpoint-merge union-find still fuses adjacent segments). Replaces the previous PCA-major-axis + bin-median approach, which projected curved roads onto a straight axis and produced wobbly / self-folding polylines. Measured on the Paris OSM trace (107 segments): mean absolute per-vertex turning angle drops from 0.456 rad → 0.127 rad (**−72%**), and mean RMS perpendicular residual drops from 1.62 m → 0.95 m (**−41%**). See `docs/bundle_tuning.md` for the table and the `polyline_mean_abs_curvature` / `polyline_rms_residual` helpers.

### Added

- **Map matching (`match-trajectory` CLI + `snap_trajectory_to_graph`)** — nearest-edge projection of a trajectory CSV onto an existing graph. Returns a `SnappedPoint(index, edge_id, projection_xy_m, distance_m, arc_length_m, edge_length_m, t)` per input sample (or `None` when the sample is farther than `--max-distance-m` / `max_distance_m`). `coverage_stats` gives the aggregate summary (matched ratio, edges touched, mean / max distance). CLI writes the per-sample details to `--output PATH.json`; the summary block is always printed to stdout. Paris self-match at 5 m tolerance: 5162 / 6634 samples matched (78 %), 239 edges touched, mean distance 1.6 m.
- **`BuildParams.post_simplify_tolerance_m`** (default 0.3 m) — final Douglas-Peucker pass runs on every edge polyline *after* X / T splits, duplicate / near-parallel merge, and junction consolidation. Drops the over-sampling the fixed-bin resample introduced (32 vertices on a 10 m straight edge → 0.3 m spacing) while keeping curvature. Paris result: total edge vertices 4905 → **1113 (−77 %)**, average vertex count 20.3 → 4.6; 8 m straight edges collapse from 32 to 2 vertices, a 1.4 km curved edge keeps 28 of its 32. Set the parameter to `None` or `0` to disable.
- **`build` / `export-bundle --extra-csv`** — primary trajectory CSV stays positional; `--extra-csv PATH` (repeatable) concatenates additional CSVs that share the same meter origin. Downstream gap-splitter still treats cross-file spatial jumps as new segments, so non-overlapping passes land as separate polylines while overlapping ones get fused by the duplicate / near-parallel merge passes. New `roadgraph_builder.io.trajectory.load_multi_trajectory_csvs()` helper for library use.
- **`sd_nav.json` respects `direction_observed`** — each edge dict now carries the `direction_observed` label and `allowed_maneuvers_reverse` is emitted as `[]` whenever the source edge was only observed `forward_only`. Edges that flip to `bidirectional` keep the full reverse-direction maneuver hints. Missing / unknown labels fall back to the pre-0.3.0 permissive behaviour (both sides populated) so hand-built graphs and legacy fixtures keep validating. `sd_nav.schema.json` documents the new field; `manifest.schema.json` is unchanged.
- **`attributes.direction_observed` on every edge** — `forward_only` when only the digitized start → end direction was observed in the source trajectory, `bidirectional` when `merge_duplicate_edges` / `merge_near_parallel_edges` folded in at least one pass that traversed the edge in the opposite direction. Downstream SD / routing consumers get an honest upper bound on one-way likelihood. `docs/map.html` popups show the label alongside the `merged_edge_count`. Paris: 38 / 242 edges are bidirectional.
- **Polyline quality metrics** — `polyline_mean_abs_curvature()` and `polyline_rms_residual()` in `roadgraph_builder.utils.geometry`. Smoothness + data-fit metrics for regression-guarding any future centerline work.
- **`LICENSE` (MIT)** — repository now ships an MIT license file, © 2026 Ryohei Sasaki; `pyproject.toml` declares `license = { file = "LICENSE" }`, author metadata, and the matching PyPI classifier. README "License" section updated from TODO to the actual notice.
- **`CONTRIBUTING.md`** — dev-setup recipe, commit / schema / data-hygiene conventions, end-to-end demo commands.
- **README badges** — CI status, MIT license, Python 3.10 / 3.12 shields.io badges at the top of the README.
- **`make docs` (pdoc)** — new optional `[docs]` extra (`pdoc>=14.0`) and a Make target that renders the public API into `build/docs/`. `build/` added to `.gitignore`.
- **`--version` / `-V` flag** — top-level argparse flag on `roadgraph_builder` prints the installed package version (`roadgraph_builder 0.3.0`) and exits 0.
- **Shell completions** — hand-written bash (`scripts/completions/roadgraph_builder.bash`) and zsh (`scripts/completions/_roadgraph_builder`) scripts cover every subcommand, the top-level `--version` / `--help`, and the common file-path arguments (`--turn-restrictions-json`, `--output`, `--origin-json`, `--lidar-points`, etc.). Install instructions added to README. A smoke test cross-checks the completion scripts against the argparse subparser list so drift gets caught on CI.
- **`docs/ARCHITECTURE.md`** — a single-page map of the codebase with Mermaid diagrams (data flow, package layout, `export-bundle` sequence, schema graph, routing subsystem, CI/release). Linked from README and PLAN so new contributors (and future sessions) can orient in one read.
- **End-to-end CLI regression test** — `tests/test_cli_end_to_end.py` shells the installed `roadgraph_builder` entry point and drives a full pipeline (`build → validate`, `export-bundle` with every optional input, then `validate-*` / `stats` / `route --output`), plus negative cases for missing input files and a `doctor` smoke. Guards argparse, exit codes, file writes, and inter-step JSON compatibility — things the in-process unit tests can miss.
- **Click-to-route in the Leaflet viewer** — `docs/map.html` now loads the map GeoJSON into a JS-side adjacency and runs a binary-heap Dijkstra when you click two graph nodes. The computed route replaces the pre-baked overlay, and a "Clear route" button / status line sits in the top bar. Works on any dataset because the data is self-contained.
- **Centerline adjacency in map GeoJSON** — `build_map_geojson` now emits `start_node_id`, `end_node_id`, and `length_m` on each centerline feature, and pins `kind: "centerline"` after the edge-attribute spread so the GeoJSON layer tag no longer collides with the internal `kind: "lane_centerline"` attribute. Existing consumers that ignored those properties are unaffected; the Leaflet viewer uses them for the client-side routing.
- **`nearest-node` CLI + `roadgraph_builder.routing.nearest_node`** — given a query point in lat/lon (with origin from `--origin-lat/--origin-lon` or `metadata.map_origin`) or in the graph's meter frame (`--xy`), return the closest `Node` id plus the straight-line distance. Returns a `NearestNode(node_id, distance_m, query_xy_m)` dataclass from Python and a JSON summary from the CLI.
- **`route --from-latlon` / `--to-latlon`** — the `route` CLI no longer forces you to know internal node ids. `from_node` / `to_node` positionals are now optional; passing `--from-latlon LAT LON` (or the `--to-*` twin) auto-snaps to the nearest node via `nearest_node`. Output adds `snapped_from` / `snapped_to` blocks with the query lat/lon and the matched node's distance, so callers can confirm the snap.
- **Route overlay in the Leaflet viewer** — `docs/map.html` now loads a dataset-specific `ROUTE_URLS` overlay on top of the primary map. `docs/assets/route_paris.geojson` ships a precomputed Paris shortest path (`n111 → n53`, 3 edges, 1267 m) so the default view shows a real route in yellow with green/red start/end dots. Legend updated to match. ODbL attribution added to `docs/assets/ATTRIBUTION.md`.
- **Route GeoJSON export** — `route --output PATH.geojson` writes a FeatureCollection with a merged route LineString (`kind="route"`), one per-edge LineString (`kind="route_edge"`, `direction`, `step`, `from_node`, `to_node`), and two Point features for the start / end nodes. Polylines walked in `reverse` direction are flipped before concatenation so the merged geometry stays in travel order. WGS84 origin is read from `--origin-lat`/`--origin-lon` or from `metadata.map_origin`; missing origin exits 1. Public helpers: `roadgraph_builder.routing.build_route_geojson` / `write_route_geojson`.
- **Turn-restriction-aware routing** — `shortest_path(..., turn_restrictions=[...])` and `route --turn-restrictions-json PATH` now search over directed states `(node, incoming_edge, direction)` and honour both `no_*` (forbid that transition) and `only_*` (whitelist at the given junction/approach). The restriction file can be a standalone `turn_restrictions.json` or any JSON with a `turn_restrictions` array (so `nav/sd_nav.json` works as-is). `Route.edge_directions` is new; the CLI output adds `edge_directions` and `applied_restrictions`.
- **`stats` CLI + public `graph_stats` / `junction_stats`** — `roadgraph_builder stats PATH.json` prints a `{graph_stats, junctions}` summary without parsing the graph yourself (edge/node count, edge length min/median/max/total, bbox in meters, optional WGS84 bbox, junction-hint and junction-type counts). Reads the WGS84 origin from `metadata.map_origin` if present, or from `--origin-lat`/`--origin-lon`. The bundle writer (`export-bundle` manifest) now shares this helper, so manifest `graph_stats` / `junctions` and the CLI output stay in sync.
- **Paris map asset for the Leaflet viewer** — `docs/assets/map_paris.geojson` (123 edges / 223 nodes, Paris 8th arr. ~2 km × 2 km, ODbL) is now the default dataset in `docs/map.html`, next to the existing Berlin OSM sample and the synthetic toy. Showcases `junction_type` on real multi-branch nodes (2× `y_junction` + 1× `complex_junction`). Raw GPS CSV is **not** committed; only the derived centerlines / boundaries / nodes ship. `docs/assets/ATTRIBUTION.md` records the sources and license.
- **`route` CLI + `roadgraph_builder.routing`** — undirected Dijkstra shortest path across the graph by edge polyline length. Usage: `roadgraph_builder route PATH.json FROM_NODE TO_NODE` prints `{from_node, to_node, total_length_m, edge_sequence, node_sequence}` as JSON. Unknown node ids exit 1 with a helpful message; disjoint components raise `ValueError`. Turn restrictions in `nav/sd_nav.json` are intentionally not applied (quick reachability, not legal routing).
- **LAZ decoding via optional `[laz]` extra** — `pip install 'roadgraph-builder[laz]'` pulls in `laspy[lazrs]`. `load_points_xy_from_las()` (and `fuse-lidar` / `export-bundle --lidar-points`) now route `.laz` through `laspy.read` when the extra is installed, otherwise raise a clear `ImportError` pointing at the install command. Uncompressed `.las` still works without the extra.

### Changed

- **CI runs `roadgraph_builder doctor`** — every CI run now exercises the doctor self-check (schema load + LAS header read) in addition to the existing validate / export-bundle steps.

## [0.3.0] — 2026-04-17

### Added

- **Distribution** — `scripts/build_release_bundle.sh` + `.github/workflows/release.yml` attach a validated `roadgraph_sample_bundle.tar.gz` (plus sha256) to every `v*` tag; a trimmed `examples/frozen_bundle/` is committed for quick inspection. `make release-bundle` wraps the script.
- **PyPI workflow scaffold** — `.github/workflows/pypi.yml` (workflow_dispatch only, PyPI / TestPyPI) builds sdist + wheel and publishes via `pypa/gh-action-pypi-publish`. Wired for Trusted Publisher OIDC; no repository secrets required. Enabling requires configuring Trusted Publishers on PyPI and a matching GitHub Environment.
- **`junction_hint: "self_loop"`** — nodes whose only incident edge is a legitimate self-loop (round trip / block circuit) are now classified as `self_loop` instead of `through_or_corner`, making large loops discoverable from topology alone.
- **`junction_type` classification** — `annotate_junction_types()` tags every `multi_branch` node with a finer geometry-derived label (`t_junction`, `y_junction`, `crossroads`, `x_junction`, `complex_junction`) based on pairwise incident-edge tangent angles. Runs automatically in `build`; non-multi-branch nodes are untouched.
- **Bundle manifest junctions** — `export-bundle`'s `manifest.json` now carries a `junctions` block with `total_nodes`, a `junction_hint` count, and a `multi_branch_types` breakdown; the same block is mirrored into `graph.metadata.export_bundle.junctions`. `docs/map.html` popups show `junction_hint` / `junction_type` for nodes.
- **Bundle manifest graph_stats** — `manifest.json` adds `graph_stats` with `edge_count`, `node_count`, `edge_length` (min/median/max/total in meters), `bbox_m`, and `bbox_wgs84_deg`; consumers can size / locate the graph without parsing `sim/road_graph.json`. Validated by `manifest.schema.json`.
- **LAS public-header reader** — `read_las_header()` (and new `LASHeader` dataclass) parses version, point count (including the LAS 1.4 extended 64-bit field), point data format / record length, scale, offset, and bbox from the fixed LAS preamble without requiring `laspy` or touching point records. Supports LAS 1.0 – 1.4; LAZ decoding still out of scope. New CLI `inspect-lidar PATH.las` prints the summary as JSON.
- **Sample LAS artefact** — `scripts/make_sample_las.py` and committed `examples/sample_lidar.las` (52 points, ~1.3 KB). `scripts/run_demo_bundle.sh` and CI now run `inspect-lidar` on the sample so LAS parsing stays exercised.
- **LAS point loader** — `load_points_xy_from_las()` returns an `(N, 2)` float64 array of X/Y in meters (scale + offset applied) without depending on `laspy`. `fuse-lidar` now dispatches on file extension: `.las` uses the LAS loader, anything else continues to read text-format CSV. CLI argument renamed `points_csv` → `points_path`.
- **`export-bundle --lidar-points PATH`** — one-shot pipeline: trajectory → HD-lite enrich → LiDAR point fusion (CSV or LAS) → camera detections → turn restrictions → three-way export. `--fuse-max-dist-m` / `--fuse-bins` tune the fusion. Manifest records `lidar_points` (path / point_count / max_dist_m / bins); `metadata.export_bundle.lidar_fuse` mirrors it. `scripts/build_release_bundle.sh` now runs with the sample LAS, so `examples/frozen_bundle/` ships LiDAR-fused boundaries.

### Changed

- **CI Node.js 24 opt-in** — every workflow sets `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` ahead of the GitHub runner switch on 2026-06-02, suppressing the deprecation warning from `actions/checkout@v4` and `actions/setup-python@v5`.
- **`doctor` self-check expanded** — checks now cover the full example tree (`turn_restrictions_sample.json`, `sample_lidar.las`, `frozen_bundle/manifest.json`, `build_release_bundle.sh`), loads every shipped JSON Schema from the package resources, and reads the bundled LAS header. Missing example files remain non-fatal, but schema-load / LAS-header failures return exit 1.

### Fixed

- **Degenerate self-loops** — `build` now drops edges whose endpoints collapse onto the same node via endpoint-merging *and* whose polyline arc length is below `2 × merge-endpoint-m`. Large legitimate loops (round trips, block circuits) are preserved. Noisy public GPS data that used to produce tens of zero-length self-loops now yields a clean graph.
- **Guard rails** — `build` / `visualize` / `export-bundle` fail with a clear message when the trajectory yields **no graph edges** (e.g. too few samples per segment), instead of writing an unusable empty graph.
- **CLI errors** — Missing input JSON/CSV files print `File not found: …` and exit 1; schema validation errors are prefixed with the file path.

### Added (pipeline backlog landed)

- **Navigation restrictions (generator)** — `export-bundle --turn-restrictions-json` plus extraction from camera detections (`kind: turn_restriction`) now populate `sd_nav.turn_restrictions`; new `validate-turn-restrictions` CLI + schema.
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

[0.3.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.3.0
[0.2.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.2.0
[0.1.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.1.0
