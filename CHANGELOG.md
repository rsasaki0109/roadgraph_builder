# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Packaging metadata now uses a SPDX license expression.**
  `pyproject.toml` now declares `license = "MIT"` with `license-files`, and
  the legacy license classifier was removed so modern setuptools builds no
  longer warn about deprecated license metadata.

### Fixed

- **Paris splitter golden length check now tolerates Python/Numpy drift.**
  The real-data splitter regression still pins edge/node IDs, but its aggregate
  length tolerance now allows the few-meter variation observed on the Python
  3.10 CI lane while keeping topology drift guarded.

## [0.7.1] — 2026-04-21

### Changed

- **README measured results are more compact.**
  The current-main validation numbers now sit near the top of `README.md` in a
  compact routing / accuracy / tuning / memory table, with the longer duplicate
  post-release table removed so the docs preview and quick-start sections are
  easier to scan.

- **Docs viewer result cards are easier to scan.**
  `docs/index.html` now has a clearer post-release results section with
  structured metric labels and updated float32 messaging. `docs/css/viewer.css`
  refreshes the palette, card spacing, focus states, and responsive metric
  grid so the SVG preview and validation numbers hold up better on desktop and
  mobile.

- **Manifest release policy is documented.**
  README and the frozen bundle notes now spell out that release-bundle tests
  normalize only `roadgraph_builder_version` and `generated_at_utc` in
  `manifest.json`; every other manifest field is part of the stable release
  surface unless changed intentionally.

- **Release bundle tests now include a byte-identity gate for stable outputs.**
  The default `export-bundle` path is rebuilt from the sample trajectory,
  detections, turn restrictions, and LiDAR fixture during tests, and stable
  generated artefacts (`sd_nav.json`, `road_graph.json`, `map.geojson`,
  `trajectory.csv`, Lanelet2 OSM, and generated README files) must match
  `examples/frozen_bundle/` byte-for-byte. The manifest is also compared after
  normalizing only `roadgraph_builder_version` and `generated_at_utc`, so
  provenance drift is caught without pinning release-time metadata.

- **Float32 drift comparison is now reproducible as a script.**
  `scripts/compare_float32_drift.py` builds float64 and opt-in float32
  bundles from the same trajectory CSV, then compares `road_graph.json`,
  `sd_nav.json`, `map.geojson`, and Lanelet2 OSM topology plus coordinate
  drift. It can write JSON/Markdown reports and fail as a release gate on
  topology change or max coordinate drift.

- **Float32 memory profiling now includes a 1M-row synthetic workload.**
  A `/tmp`-only 1,000,000-row trajectory profile shows the expected
  `Trajectory.xy` allocation drop from 24,000,568 B to 16,000,568 B and a
  tracemalloc peak drop of about 19 MB, while process RSS after full
  `export-bundle` only falls by about 2.6 MB because large temporary build and
  GeoJSON serialization allocations dominate the high-water mark.

- **Float32 memory profiling now includes an OSM public-trace replay stress.**
  A `/tmp`-only replay built from Paris, Tokyo, and Berlin public trackpoints
  shows the same direct XY allocation saving, but full `export-bundle` RSS on
  a 75k-row replay only falls by about 4 MB and the drift comparator reports
  edge / Lanelet ID instability under float32. The default therefore remains
  float64.

- **README release surface is now explicit about shipped vs post-release work.**
  The README separates the v0.7.0 shipped command surface from v0.7.1
  measured results, so validation numbers, docs preview status, and float32
  drift measurements read as patch-release follow-up work rather than part of
  the original v0.7.0 tag. It also removes stale "trajectory CSV only" and shell
  completion caveats.

- **CLI command boundaries are now split by domain.**
  `roadgraph_builder/cli/main.py` is now a thin dispatcher with shared loading
  helpers. Command parser/handler code lives in domain modules:
  `build`, `validate`, `routing`, `export`, `camera`, `lidar`, `osm`,
  `guidance`, `trajectory`, `hd`, `incremental`, and `dataset`.
  Each split adds direct handler tests with injected I/O so command behavior
  can be verified without subprocess-only coverage.

- **README / GitHub Pages now surface measured results.**
  README adds a compact measured-results table for the Paris TR-aware route,
  lane-count accuracy baselines, cross-city bundle tuning, and float32 drift
  report. The GitHub Pages diagram viewer adds matching metric cards below the
  Paris route preview so the live docs show both the visualization and the
  latest validation numbers.

- **README / GitHub Pages now show a polished Paris route visualization.**
  `docs/images/paris_grid_route.svg` is generated from the committed Paris
  OSM-highway GeoJSON, TR-aware route overlay, and turn-restriction JSON.
  README embeds the preview and links to the interactive Pages map; the Pages
  diagram viewer adds a compact result card below the live SVG viewer.

- **Bundle tuning now includes a Berlin Mitte public-GPS sweep.**
  `docs/bundle_tuning.md` adds a third real-data OSM public trackpoints
  sample (`13.3700,52.5100,13.4000,52.5250`, 7500 points) with the same
  `max-step-m` / `merge-endpoint-m` sweep used for Paris and Tokyo. The
  result keeps `--max-step-m 40 --merge-endpoint-m 8` as the conservative
  cross-city starting point, with bundle validation passing for the Berlin
  `40/8` artefact.

- **CLI completions now cover the v0.6/v0.7 command surface.**
  Bash and zsh completions include the lane-count, Lanelet2 validation,
  camera lane-detection, incremental update, and dataset batch commands added
  after v0.5, with common new flags such as `--per-lane`,
  `--allow-lane-change`, `--ground-plane`, and `--lane-markings-json`.
  The completion smoke test now derives the expected subcommands from the
  argparse parser so future CLI additions cannot silently drift.

- **V1 follow-up: Paris 20e now uses the same canonical 20 m accuracy run.**
  `docs/accuracy_report.md` replaces the placeholder shipped-CSV note with a
  live Overpass measurement for bbox `2.3900,48.8450,2.4120,48.8620`:
  794 ways / 3471 nodes, 245 ways with `lanes=`, 997-edge graph,
  193/997 matched at 20 m, **MAE = 0.938 lanes**.

- **V1 follow-up: real-data α accuracy numbers for Tokyo Ginza + Berlin Mitte.**
  `docs/accuracy_report.md` replaces the `[not yet measured]` rows with
  Overpass-fetched numbers captured 2026-04-20: Tokyo Ginza (`139.7600,
  35.6680,139.7750,35.6750`, 415 ways / 1891 nodes) → 598-edge graph,
  113/598 matched at 20 m, **MAE = 0.903 lanes**; Berlin Mitte (`13.3700,
  52.5100,13.4000,52.5250`, 1659 ways / 4748 nodes) → 1640-edge graph,
  531/1640 matched at 20 m, **MAE = 1.220 lanes**. Both are `source=default`
  baselines (no LiDAR markings / trace_stats) and document the 20 m canonical
  tolerance vs the original 5 m recipe.

- **V3 follow-up: float32 trajectory optimization now has an opt-in prototype.**
  `docs/handoff/float32_trajectory.md` records the dtype flow and
  byte-identity impact matrix. `load_trajectory_csv(..., xy_dtype="float32")`,
  `BuildParams(trajectory_xy_dtype="float32")`, CLI `--trajectory-dtype
  float32`, and `scripts/profile_memory.py --trajectory-dtype float32` now
  allow explicit coordinate-array memory experiments while default trajectory
  loading remains float64. `docs/float32_drift_report.md` records the first
  float64/float32 comparison: topology unchanged on Paris and Berlin samples,
  <1 mm max coordinate drift, but no process-level RSS win large enough to
  justify a default change.

### Fixed

- **V1: `measure_lane_accuracy.py` now handles meter-frame graphs.** When the
  graph JSON carries `metadata.map_origin` (written by `build-osm-graph` with
  an origin), OSM node lon/lat are converted to the same local ENU frame
  before the centroid-distance check, instead of silently comparing meters to
  degrees. Synthetic fixtures without `map_origin` keep the original
  haversine path. New unit test:
  `test_map_origin_converts_osm_to_meter_frame`.

- **3D2: silence `RuntimeWarning: invalid value encountered in divide` from
  `_rgb_to_hsv`.**  Line `delta / cmax` at `lane_detection.py:100` warned on
  pure-black pixels (0/0) because `np.where` evaluates both branches before
  selecting; rewritten to `np.divide(..., where=cmax > 0)` with a
  zero-initialised out buffer.  Running the full suite under
  `-W error::RuntimeWarning` now reports zero warnings (previously 6 tests
  raised on this path).

- **Perf flake: isolate the 50×50 grid wall-time test under `@pytest.mark.slow`.**
  `test_50x50_grid_within_budget` sat at ~22 s against a 30 s budget, so
  loaded CI would intermittently breach the budget. Budget widened to 60 s
  and tagged `slow`; `pyproject.toml` now excludes both `city_scale` and
  `slow` markers from the default run (`-m 'not city_scale and not slow'`).
  Opt-in: `pytest -m slow`. Side effect: default `make test` drops from
  ~56 s → ~27 s.

## [0.7.0] — 2026-04-20

### Added

- **V2: City-scale OSM regression tests** — `tests/test_city_scale.py` (3 parametrised tests: Paris 20e arr., Tokyo Setagaya, Berlin Neukölln) fetches OSM highways via Overpass, builds a graph, exports a bundle to `/tmp/`, and asserts edge_count ≥ threshold + zero degenerate self-loops. Tests are tagged `@pytest.mark.city_scale`; `pyproject.toml` registers the marker and adds `addopts = "-m 'not city_scale'"` so plain `pytest` / `make test` skips them (3 deselected). Run with `pytest -m city_scale`. `.github/workflows/city-bench.yml` is a manual `workflow_dispatch` workflow (no `on: push` / `on: schedule`); stores bundle artefacts + console output as GitHub Actions artefacts.

- **V1: Real-data α lane-count accuracy campaign** — `scripts/measure_lane_accuracy.py` matches graph edges (with `hd.lane_count` from `infer-lane-count`) to OSM way `lanes=` tags via centroid proximity (default 5 m) and tangent alignment (cosine ≥ 0.7). Emits confusion matrix, MAE, per-pair detail JSON. `docs/accuracy_report.md` records the Paris 20e arr. / Tokyo Ginza / Berlin Mitte bbox recipe; Paris numbers are from the shipped OSM public GPS graph (all edges default `lane_count=1` without lane markings); Tokyo Ginza and Berlin Mitte are marked `[not yet measured]` pending a live Overpass fetch. Not run by CI (`make accuracy-report` recipe in docs).

- **A2: Autoware `lanelet2_validation` round-trip bridge** — new `roadgraph_builder/io/export/lanelet2_validator_bridge.py` module shells out to `lanelet2_validation --map-file <path>` when it is on PATH and parses stdout/stderr for error / warning counts (summary-line regex with line-count fallback). Returns a structured dict `{status, errors, warnings, error_lines, return_code}`. CLI: `validate-lanelet2 map.osm [--timeout N]` — exits 0 when the tool is absent (skip JSON `{"status": "skipped"}` on stdout + warning on stderr) or when errors=0; exits 1 on ≥1 error with structured JSON on stdout and error summaries on stderr. Distinct from `validate-lanelet2-tags` (tag completeness only).
- **A3: Lane-change routing + Lanelet2 `lane_change` relation** — `shortest_path` gains `allow_lane_change` / `lane_change_cost_m` parameters extending the Dijkstra state to `(node, incoming_edge, direction, lane_index)`. Lane swaps within the same edge cost `lane_change_cost_m` (default 50 m). The returned `Route.lane_sequence` carries the per-step lane index (None when `allow_lane_change=False`). `export_lanelet2_per_lane` gains a `lane_markings` parameter and now tags each `lane_change` relation with `sign=solid` (solid boundary → prohibited) or `sign=dashed` (dashed / unknown → permitted); without `lane_markings` the sign defaults to `dashed`. CLI: `route --allow-lane-change [--lane-change-cost-m M]`.
- **A1: Full traffic_light / stop_line regulatory_element wiring** — `export_lanelet2` gains a `camera_detections` parameter (and the `export-lanelet2 --camera-detections-json` CLI flag) that wires detections from a `camera_detections.json` into the Lanelet2 OSM output. `kind=traffic_light` observations produce a `type=regulatory_element, subtype=traffic_light` relation with a `refers` node at the detection world position; `kind=stop_line` observations with a `polyline_m` produce a `type=line_thin, subtype=solid` way. When `camera_detections` is `None` (the default), output is byte-identical to v0.6.0 δ. Existing `validate-lanelet2-tags` passes on the enriched output.
- **3D2: Camera-only lane detection** — `roadgraph_builder/io/camera/lane_detection.py` adds pure-NumPy HSV conversion (`_rgb_to_hsv`), 4-connected component labeling (`_fast_connected_components`), and the main detector `detect_lanes_from_image_rgb` which returns `LinePixel` objects for white and yellow markings without any cv2/scipy dependency. `project_camera_lanes_to_graph_edges` back-projects pixel centroids through a pinhole camera model (`CameraCalibration` + `pixel_to_ground`) into world frame and snaps them to the nearest graph edge within a distance gate, returning `LaneMarkingCandidate` results. CLI: `detect-lane-markings-camera --image ... --calibration-json ... --graph-json ... --pose-json ...`; result is a JSON list of candidates. Omitting the command leaves all other outputs byte-identical.
- **3D3: LiDAR ground-plane RANSAC + true-3D fuse** — `fit_ground_plane_ransac` in `roadgraph_builder/hd/lidar_fusion.py` fits a dominant plane from an (N,3) point cloud using RANSAC (seeded, NumPy only, 200-iter default). Returns normalised plane normal (always z ≥ 0) and offset. `fuse_lane_boundaries_3d` applies the filter before the existing binned-median 2D fusion: only points within `height_band_m` (default 0–0.3 m) above the ground plane pass through, discarding vegetation and overhead structures. `metadata.lidar` gains `ground_plane_normal`, `ground_plane_d`, `ground_plane_height_band_m`, `ground_plane_filtered_out`, `ground_plane_kept`. CLI: `fuse-lidar --ground-plane` gate; omitting it is byte-identical to v0.6.0. `io/lidar/las.py` gains `load_points_xyz_from_las` (N,3 XYZ); `io/lidar/points.py` gains `load_points_xyz_csv` (N,3 or N,4 XYZ[I]).
- **3D1: 3D / elevation throughout** — `build --3d` reads optional `z` column from trajectory CSV and propagates elevation data through the graph. `edge.attributes.polyline_z` (per-vertex z list), `edge.attributes.slope_deg` (signed, positive = uphill in forward direction), and `node.attributes.elevation_m` are added in 3D mode. `enrich_sd_to_hd` mirrors slope_deg and elevation_m into `hd` blocks. `export-lanelet2` emits `<tag k="ele" .../>` on graph nodes when elevation data is present. `route --uphill-penalty` / `--downhill-bonus` multiply edge cost based on slope direction; omitting these flags leaves routing byte-identical to v0.6.0. `road_graph.schema.json` gains optional `point2or3` (x/y/z polyline vertex), `slope_deg`, `polyline_z`, and `elevation_m` fields — all optional so existing 2D graphs validate unchanged.
- **P3: Dataset-level batch CLI (`process-dataset`)** — `roadgraph_builder/cli/dataset.py` adds `process_dataset()` which iterates CSV files in a directory, calls `export_map_bundle` on each, and aggregates results into `dataset_manifest.json`. Per-file errors are isolated by default (`--continue-on-error`); the manifest records `status=failed` + error message for any failed file. `--parallel N` distributes work across N worker processes via `ProcessPoolExecutor`. CLI: `roadgraph_builder process-dataset input_dir/ output_dir/ --origin-json ... --pattern "*.csv"`.
- **P2: Incremental / streaming build (`update-graph` CLI)** — `roadgraph_builder/pipeline/incremental.py` adds `update_graph_from_trajectory` which merges a new trajectory into an existing graph without a full rebuild. New polylines that fall entirely within `absorb_tolerance_m` of an existing edge bump `trace_observation_count` rather than creating a new edge; unabsorbed polylines go through a restricted X/T split + endpoint union-find restricted to nearby edges. CLI: `roadgraph_builder update-graph existing.json new.csv --output merged.json`.

### Changed

- **V3: Memory profile + optimization** — `scripts/profile_memory.py` uses `tracemalloc` to snapshot allocations at four pipeline stages (imports / trajectory load / build / export-bundle) and writes `docs/memory_profile_v0.7.md` with top-20 allocator table and peak RSS per stage. Hotspot fix: `export_lanelet2` / `export_lanelet2_per_lane` replaced the `minidom.parseString → toprettyxml` round-trip with a direct `_et_to_pretty_bytes` recursive chunk-writer that produces byte-identical output while eliminating ~900 KB of DOM object allocation. Measured peak RSS on Paris trackpoints CSV: **61 028 KB → 54 944 KB (−10.0 %)**.

- **P1: X/T-junction split O(N²) → O(N log N)** — new `roadgraph_builder/pipeline/crossing_splitters.py` module replaces the brute-force pair scan in `split_polylines_at_crossings` / `split_polylines_at_t_junctions` with a uniform grid hash. X-crossings index segments per cell; T-junctions use a polyline-bbox grid with inverted endpoint→polyline lookup. Result is numerically identical to the O(N²) path on all inputs including Paris real data. `scripts/run_benchmarks.py` benchmark `polylines_to_graph_10k_synth` restored to a 50×50 grid (~25 000 points); target ≤ 30 s on the fast path.

## [0.6.0] — 2026-04-20

### Added

- **`infer-lane-count` CLI + per-lane Lanelet2 export (`export-lanelet2 --per-lane`)** — `roadgraph_builder/hd/lane_inference.py` infers per-edge lane count and per-lane centerlines from `lane_markings.json` (1-D agglomerative clustering of paint-marker lateral offsets) with fallback to `trace_stats.perpendicular_offsets` mode counting; results written into `attributes.hd.lane_count` / `attributes.hd.lanes[]`. `export_lanelet2_per_lane` expands each edge with `hd.lanes` data into one lanelet per lane (with `roadgraph:lane_index` tag) and emits `lane_change` regulatory_element relations for adjacent pairs; edges without lane data fall back to the standard 1-lanelet/edge output. `road_graph.schema.json` gains optional `lane_count` (int, 1–6) and `lanes[]` (array with `lane_index` / `offset_m` / `centerline_m` / `confidence`) fields in the `hd_block` definition.
- **Lanelet2 fidelity upgrade (`export-lanelet2 --speed-limit-tagging` / `--lane-markings-json` + `validate-lanelet2-tags` CLI)** — `export-lanelet2` gains `--speed-limit-tagging regulatory-element` (emits a separate `type=regulatory_element, subtype=speed_limit` relation instead of an inline tag, matching the Lanelet2 spec) and `--lane-markings-json` (derives `subtype=solid|dashed` on boundary ways from paint intensity heuristic). New `validate-lanelet2-tags` CLI parses an OSM file and reports missing required tags (`subtype`, `location`) on lanelet relations as errors and missing `speed_limit` as warnings; exits 1 on schema-level violations. Four helper functions added to `io/export/lanelet2.py`: `_speed_limit_tags`, `_lane_marking_subtype`, `_build_speed_limit_regulatory`, `_build_right_of_way_regulatory`. All new flags default to 0.5.0 behavior when omitted.
- **Uncertainty-aware routing (`route --prefer-observed` / `--min-confidence`)** — `shortest_path` gains optional cost hooks: `prefer_observed=True` multiplies observed-edge costs by `observed_bonus` (default 0.5) and unobserved-edge costs by `unobserved_penalty` (default 2.0), favouring edges with `trace_observation_count > 0`; `min_confidence` excludes edges whose `hd_refinement.confidence` is below the threshold from Dijkstra expansion, exiting with a clear error message when the destination is unreachable. Both hooks default to off so existing callers are byte-identical to 0.5.0. `total_length_m` is now always the true arc length (not the weighted Dijkstra cost), ensuring route distances stay in real meters regardless of cost multipliers.

## [0.5.0] — 2026-04-20

### Added

- **`detect-lane-markings` CLI** — per-edge LiDAR intensity-peak extraction that recovers left/right/center lane marking candidates from a LAS point cloud without ML; writes `lane_markings.json` validated by `lane_markings.schema.json`.
- **`guidance` CLI** — converts a route GeoJSON + sd_nav.json into a turn-by-turn GuidanceStep sequence (depart/arrive/straight/left/right/…) with signed heading-change angles; writes `guidance.json` validated by `guidance.schema.json`.
- **`make bench` + `scripts/run_benchmarks.py`** — deterministic wall-clock benchmarks for graph build, synthetic grid, 100 shortest-path queries, and export-bundle; `--baseline` mode exits 1 on ≥ 3× regression; `docs/benchmarks.md` records v0.5.0 baseline numbers.
- **HD-lite multi-source refinement (`enrich --lane-markings-json` / `--camera-detections-json`)** — `roadgraph_builder/hd/refinement.py` fuses lane-marking candidates, trace_stats, and camera observations into per-edge `hd_refinement` metadata with refined half-width and confidence; `enrich_sd_to_hd` accepts an optional `refinements=` list; `export-bundle` exposes `--lane-markings-json` / `--camera-detections-refine-json` flags.

## [0.4.0] — 2026-04-19

### Changed

- **CI activates the optional-dependency regression paths** — `.github/workflows/ci.yml` now installs `[dev,laz]` + `opencv-python-headless` + `actions/setup-node@v4` before running pytest, so the three previously-skipping regression paths run on every push: `tests/test_las_cross_format.py` (12 parametrised LAS version × PDRF combos via `laspy`), `tests/test_camera_distortion.py::test_undistortion_matches_cv2` (our fixed-point inversion vs `cv2.undistortPointsIter`), and `tests/test_viewer_js_dijkstra.py` (the viewer TR-aware Dijkstra smoke via Node.js 24). Skip-on-missing logic is preserved so a bare `[dev]` local install still passes.

### Added

- **Embedded attribution + license on OSM-derived assets** — `export_map_geojson`, `write_route_geojson` and `convert-osm-restrictions` now accept optional `attribution` / `license_name` / `license_url` parameters that get embedded in the output file's top-level `properties` (geojson) or as top-level siblings of `turn_restrictions` (TR JSON). `turn_restrictions.schema.json` gained three optional fields for the same trio. All six shipped OSM-derived assets (`map_osm.geojson`, `map_paris.geojson`, `route_paris.geojson`, `map_paris_grid.geojson`, `route_paris_grid.geojson`, `paris_grid_turn_restrictions.json`) are rebaked with `"© OpenStreetMap contributors"` + `"ODbL-1.0"` + the opendatacommons URL, so consumers who see only one file still know where it came from. `docs/assets/ATTRIBUTION.md` still ships as the canonical attribution manifest alongside. `tests/test_attribution.py` guards the pass-through on both exporters plus a shipped-asset regression so future re-bakes can't accidentally drop the fields.
- **Turn-restriction-aware client-side routing in the Leaflet viewer** — `docs/map.html`'s JS Dijkstra is now a directed-state router over `(node, incoming_edge, direction)` that honours both `no_*` and `only_*` turn restrictions loaded from `RESTRICTIONS_URLS`. Click-to-route on the `paris_grid` dataset respects the 10 OSM restrictions baked into `docs/assets/paris_grid_turn_restrictions.json`, and the status line reports `… TR honoured` when restrictions are active. `tests/test_viewer_js_dijkstra.py` + `tests/js/test_viewer_dijkstra.mjs` pull the two functions out of `map.html` and smoke-test them against a tiny fixture that forces a 30 m detour from the unrestricted 20 m baseline (verified separately for `no_left_turn` and `only_right_turn`). Skipped gracefully when Node.js isn't on PATH.
- **Brown-Conrady lens distortion (`CameraIntrinsic.distortion` + `undistort_pixel_to_normalized`)** — `CameraIntrinsic` now carries an optional 5-coefficient distortion tuple `(k1, k2, p1, p2, k3)` in OpenCV order. A fixed-point iteration inverts the Brown-Conrady forward model to recover the undistorted normalized camera ray for a distorted pixel. `pixel_to_ground` picks this path automatically whenever distortion is present; the no-distortion case falls back to the original `K^{-1} * [u, v, 1]`. Cross-checked against `cv2.undistortPointsIter` at ≤ 1e-6 on realistic automotive-grade wide-angle distortion. Calibration JSON round-trips the coefficients via the `distortion: {k1, k2, p1, p2, k3}` object so existing calibration files without a `distortion` key continue to load as undistorted.
- **Self-contained camera pipeline demo** — `scripts/generate_camera_demo.py` forward-projects a handful of ground-truth world-frame features (lane marks at ±1.75 m, a stop line, two speed-limit signs) through a 1280×800 wide-angle camera with Brown-Conrady distortion `(-0.27, 0.09, 0.0005, -0.0003, -0.02)` across a four-pose simulated drive. Writes `examples/demo_camera_calibration.json` + `examples/demo_image_detections.json` with each detection carrying its ground truth in `_world_ground_truth_m`. `tests/test_camera_demo_roundtrip.py` runs the shipped demo through `project_image_detections_to_graph_edges` and asserts the max recovery error stays under 10 cm — on the shipped files it's ~1 cm, bounded by the 0.1-px pixel rounding. `docs/camera_pipeline_demo.md` walks through the demo and points at a real-data recipe (Mapillary CC-BY-SA or KITTI).
- **Camera image → graph-edge pipeline (`project-camera` CLI + `roadgraph_builder.io.camera`)** — pinhole projection from image pixels to the world ground plane, followed by nearest-edge snap, producing the same `camera_detections.schema.json` shape that `apply-camera` already consumes. Three new layers: `CameraCalibration` (intrinsic K + rigid `camera_to_vehicle` mount in body FLU, loaded from JSON with `rotation_rpy_rad` or an explicit 3×3 matrix), `pixel_to_ground` (per-pixel ray construction through `K^{-1}` → body frame → world, intersected with a horizontal ground plane at `--ground-z-m`), and `project_image_detections_to_graph_edges` (full image-detections → projections → `snap_trajectory_to_graph` within `--max-edge-distance-m`). Above-horizon rays and detections without a nearby edge are dropped and counted in the returned `CameraProjectionResult`. The CLI takes calibration JSON + per-image pixel detections JSON + graph JSON and writes the edge-keyed observations, so the end-to-end chain `images → detections → export-bundle` now has a real first stage. Example files (`examples/camera_calibration_sample.json`, `examples/image_detections_sample.json`) + 11 new tests (principal-pixel horizontal miss, 45° ground-hit, right-side projection, vehicle yaw rotation, above-horizon drop, example-file roundtrip, edge-snap end-to-end, no-nearby-edge drop, CLI smoke).
- **Cross-format LAS regression tests + real-data verification** — `tests/test_las_cross_format.py` uses `laspy` (the existing `[laz]` extra) to generate a LAS file for every point data record format we claim to support (PDRF 0-10, LAS 1.2 / 1.3 / 1.4) and asserts our pure-Python `read_las_header` / `load_points_xy_from_las` produce byte-identical XY to `laspy.read`. Includes a 70 000-point LAS 1.4 PDRF 6 file that exercises the 64-bit extended point count field at header offset 247. Skipped when `laspy` isn't installed so CI without the extra still passes. Verified out-of-band against 7 real PDAL test LAS files (autzen_trim 3.7 MB / 110 K pts, 4_1 LAS 1.4 PDRF 1, 4_6 LAS 1.4 PDRF 6, mvk-thin LAS 1.2 PDRF 1, interesting / simple / 100-points LAS 1.2 PDRF 3) — all 7 parse and cross-match laspy; `fuse-lidar` on autzen_trim writes per-edge `lane_boundaries` with real 110 K-point coverage.
- **OSM turn restrictions → graph-space `turn_restrictions.json`** — new `build-osm-graph` and `convert-osm-restrictions` CLI subcommands (+ `roadgraph_builder.io.osm.{build_graph_from_overpass_highways,convert_osm_restrictions_to_graph}`). The first rebuilds a topologically honest road graph by treating each drivable `way["highway"~...]` as a polyline and running the existing X/T-split + endpoint union-find pipeline, so every OSM junction becomes a graph node with `metadata.map_origin` preserved. The second snaps OSM `type=restriction` relations onto that graph: via-node to nearest graph node within `--max-snap-m` (default 15 m), then picks incident edges whose tangent at the junction best aligns (`cos ≥ --min-alignment`, default 0.3) with each OSM way's direction away from the via-node. `no_u_turn` / same-way from+to allow `from_edge == to_edge`. Unsupported `restriction` tags and unmappable relations land in `--skipped-json` with explicit reasons. Paris 2.3370–2.3570°E × 48.8570–48.8770°N verification: **10 / 11 real OSM restrictions mapped** (the 11th references a way classified outside the drivable set); the restricted-`route` detour from `n312 → n191` extends from 878 m → 909 m compared to the unrestricted shortest path.
- **OSM fetch scripts** — `scripts/fetch_osm_turn_restrictions.py` and `scripts/fetch_osm_highways.py` pull raw Overpass JSON for a bbox. Both support `--endpoint` / `OVERPASS_ENDPOINT` so users can fall back to mirrors (`overpass.kumi.systems`, `overpass.private.coffee`) when the main instance is saturated. Output stays under `/tmp` by policy — derivatives (graph JSON, turn_restrictions JSON) are what gets committed.
- **Paris turn_restrictions viewer demo** — `docs/assets/map_paris_grid.geojson` (855 nodes / 1081 edges, compact JSON, ~470 KB), `docs/assets/paris_grid_turn_restrictions.json` (10 OSM restrictions) and `docs/assets/route_paris_grid.geojson` (the restriction-aware `n312 → n191` path) are now the default overlay of `docs/map.html`. Restrictions render as red dots at each junction_node with popups showing the restriction type + from/to edges; the legend gets a matching entry. Selecting the older **Paris (OSM public GPS traces)** layer still works — the new dataset is added alongside, not replacing. `docs/assets/ATTRIBUTION.md` documents the provenance and includes the refetch recipe.



- **Junction cluster consolidation** — new `consolidate_clustered_junctions` pass runs at the end of `polylines_to_graph`. It finds pairs of `multi_branch` nodes within `1.75 × merge_endpoint_m` of each other, union-finds them into a single cluster, collapses each cluster to one node at the centroid, and rewrites incident edges. Cleans up the case where one real intersection is split across two or three anchor points because different polylines reached the junction from slightly different directions. Paris: 1 node absorbed (conservative tolerance keeps the effect small).
- **Near-parallel edge merge** — new `merge_near_parallel_edges` pass runs after the exact-duplicate merge. For every pair of edges whose endpoint-to-endpoint distance sum is below `2 * merge_endpoint_m` (both forward and reversed pairings are considered), the corresponding node ids are union-found into a single cluster. Each cluster collapses to one node at the cluster's centroid, edges are rewritten, and the follow-up duplicate merge averages what are now identical endpoint pairs. Paris OSM: edges 247 → 242, nodes 254 → 250, LCC unchanged at 53 %. Catches the "same road walked twice, each pass anchoring to a slightly different junction cluster" case that exact-duplicate folding missed.
- **Duplicate edge merge** — `polylines_to_graph` now folds edges that share the same (start, end) node pair (regardless of direction) into a single edge. Each polyline is resampled at `centerline_bins` arc-length-uniform samples, reversed when walked in the opposite canonical direction, and per-sample averaged. The merged edge stores `attributes.merged_edge_count`, so downstream consumers can see "this centerline is the average of N passes". On the Paris OSM trace: edges 347 → **247** (100 redundant passes absorbed into 71 averaged centerlines). The largest connected component is unchanged (135 / 53 %); previously-phantom `multi_branch` nodes that were only branching via duplicates collapse back to `through_or_corner`, so the node classification distribution is more honest (`multi_branch` 112 → 67).
- **Miter-joined lane offsets** — `centerline_lane_boundaries` replaces the previous central-difference unit-normal offset with a proper miter join: interior vertices sit on the angle bisector of the two adjacent edge normals at the miter length that keeps perpendicular distance to each incident infinite edge-line equal to the configured half-width. Near-180° reversals fall back to a bevel (two separate offset vertices) once the miter would exceed `miter_limit * half_width`. The old code kept the ribbon a roughly constant chord-distance from the centerline, which under-offset on the inside of sharp curves and flared on the outside; the new version behaves correctly on straight, 90°, and hairpin samples. No public API break; `centerline_lane_boundaries(polyline, lane_width_m)` still returns `(left, right)` polylines, optionally with `miter_limit=4.0` for custom join clamping.
- **X-junction splitting in `build`** — `polylines_to_graph` now runs `split_polylines_at_crossings` before the T-junction / union-find passes. Every pair of polylines whose interiors strictly cross is cut at the intersection, so crossings become real junction nodes instead of phantom unrelated edges. Bounding-box pre-filter keeps the pair scan tractable. On the Paris OSM trace the accumulated splitting (X + T + endpoint merge) now yields 347 edges / 254 nodes, a **135-node largest connected component (53 % of the graph)**, and correct labelling of 18 `x_junction` + 8 `crossroads` nodes that used to collapse into `complex_junction`. The viewer now draws a 19-edge 1923 m Dijkstra route across the LCC.
- **T-junction splitting in `build`** — `polylines_to_graph` now calls a new `split_polylines_at_t_junctions` pass before endpoint union-find: whenever one polyline's endpoint lands within `merge_endpoint_m` of another polyline's *interior* (not its own endpoint), the target polyline is split at the projection so both sides share a junction vertex the union-find can fuse. Guarded by `min_interior_m=1.0` so we don't double-split at tip-to-tip cases the old endpoint-merge already handles. Paris OSM result (`--max-step-m 40 --merge-endpoint-m 8`): edges 123 → 221, largest connected component 5 → **84 nodes** (40 % of the graph), `multi_branch` nodes 3 → 72 (12 `t_junction` + 37 `y_junction` + 23 `complex_junction`). The viewer now draws a 3 km 6-edge route along the connected component; before, no path longer than ~1 km existed.
- **Centerline smoothing upgrade** — `centerline_from_points` now walks the time-ordered segment, computes cumulative arc length, and resamples at ``num_bins`` positions using a Gaussian window in arc-length space (raw first/last points are anchored so the endpoint-merge union-find still fuses adjacent segments). Replaces the previous PCA-major-axis + bin-median approach, which projected curved roads onto a straight axis and produced wobbly / self-folding polylines. Measured on the Paris OSM trace (107 segments): mean absolute per-vertex turning angle drops from 0.456 rad → 0.127 rad (**−72%**), and mean RMS perpendicular residual drops from 1.62 m → 0.95 m (**−41%**). See `docs/bundle_tuning.md` for the table and the `polyline_mean_abs_curvature` / `polyline_rms_residual` helpers.
- **Trace fusion (`fuse-traces` CLI + `fuse_traces_into_graph()`)** — hold the graph fixed, overlay multiple trajectories (typically one per day / per drive), and record per-edge observation stats in `attributes.trace_stats`: `trace_observation_count` (how many independent traces hit this edge), `matched_samples`, `first_observed_timestamp` / `last_observed_timestamp`, plus hour-of-day and weekday bin counts (UTC; populated only when timestamps look epoch-like). `coverage_buckets()` groups edges by 0 / 1 / 2+ / 5+ trace observations to surface "backbone vs. observed once" at a glance. Paris 5-trace public-GPS verification (same 242-edge graph, 5 separate pages re-projected to a shared origin): **240 / 242 edges observed; 118 validated by ≥ 2 traces**; the busiest edge appears on 4 traces spanning hours 9 / 11 / 14 / 20.
- **Signalized-junction inference (`infer-signalized-junctions` CLI + `infer_signalized_junctions()`)** — detect stop windows in the trajectory (median speed below `--stop-speed-mps` held for ≥ `--stop-min-duration-s`), snap each stop centroid to the nearest graph node within `--max-distance-m`, and tag nodes that accumulate ≥ `--min-stops` independent stops with `attributes.signalized_candidate = true`, `stop_event_count`, and `stop_event_total_seconds`. Not a ground-truth signal detector — catches signals, stop signs, congestion hot-spots, parking pauses alike — but useful as candidate review signal. `detect_stop_events()` is exported as a lower-level helper. Paris OSM verification: **13 nodes** flagged, top candidate with 8 observed stops.
- **Trip reconstruction (`reconstruct-trips` CLI + `reconstruct_trips()`)** — partition a long GPS trace into discrete trips using three signals: time gaps (`--max-time-gap-s`), spatial gaps (`--max-spatial-gap-m`), and stop windows (`--stop-speed-mps` held for ≥ `--stop-min-duration-s`). Each trip is snapped to the graph (configurable `--snap-max-distance-m`) and returned as `Trip(trip_id, start/end index/timestamp/xy, start/end edge id, edge_sequence, sample/matched counts, total_distance_m, mean_speed_mps)`. `trip_stats_summary` aggregates the batch. Small / short trips are filtered out (`--min-trip-samples`, `--min-trip-distance-m`). Paris OSM public-GPS verification (6634 samples merged from 5 separate traces): **130 trips reconstructed, 91 % samples matched, 36.4 km total distance / 7 h 14 m total duration, longest trip 1.3 km over 29 edges**.
- **Lanelet2 lane-connection relations** — `export-lanelet2` now emits a `type=regulatory_element, subtype=lane_connection` relation per graph junction node that touches ≥ 2 lanelets. Members are the incident lanelet relations with role `from_start` / `from_end` (indicating which endpoint of the underlying edge anchors the junction). Tags include `roadgraph:junction_node_id`, `roadgraph:junction_type`, and `roadgraph:junction_hint` so downstream Lanelet2 tooling can reconstruct SD-level graph connectivity directly from the OSM document instead of re-inferring it from shared boundary points.
- **HMM map matching (`match-trajectory --hmm` + `hmm_match_trajectory`)** — Viterbi-decode the trajectory over per-sample candidate edges within `--max-distance-m`. Emission cost is a Gaussian on the GPS distance (`--gps-sigma-m`); transition cost penalises large differences between the GPS step and the graph shortest-path distance between candidate projections (capped at `--transition-limit-m`). Resolves the "parallel streets alias" failure mode of the per-sample nearest-edge matcher. Same CLI subcommand as before — just pass `--hmm` to switch algorithms. The stats block reports `algorithm: "hmm_viterbi"` vs `"nearest_edge"` so downstream analytics can tell the outputs apart.
- **Road class inference (`infer-road-class` CLI + `infer_road_class()`)** — snap the source trajectory onto the built graph, compute per-edge speeds from consecutive same-edge samples, and classify each edge as `highway` / `arterial` / `residential` by the median observed speed. Writes `attributes.observed_speed_mps_median`, `attributes.observed_speed_samples`, and `attributes.road_class_inferred` on every edge that saw ≥ `--min-samples` observations. Thresholds are configurable (`--highway-mps` / `--arterial-mps`). Paris measurement: 175 of 242 edges classified (174 residential + 1 arterial; 67 lacked enough observations).
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

[0.7.1]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.7.1
[0.7.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.7.0
[0.6.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.6.0
[0.5.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.5.0
[0.4.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.4.0
[0.3.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.3.0
[0.2.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.2.0
[0.1.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.1.0
