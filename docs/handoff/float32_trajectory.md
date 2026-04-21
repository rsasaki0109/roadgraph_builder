# Float32 trajectory optimization design memo

Date: 2026-04-21

Status: design complete, opt-in prototype landed, and first measurement
recorded in `docs/float32_drift_report.md`.  The default remains float64.

## Goal

Reduce peak memory from trajectory coordinate arrays while preserving the
current default outputs.  The v0.7 memory profile already removed the
Lanelet2 DOM round-trip and dropped Paris peak RSS by about 10%; the remaining
candidate is the trajectory `xy` array, which is currently float64.

## Non-goals

- Do not change default output bytes in `build`, `visualize`, `export-bundle`,
  `process-dataset`, or the docs asset refresh.
- Do not downcast LiDAR, camera calibration, camera projection, lane-detection,
  or 3D elevation arrays in this workstream.
- Do not refactor `Edge.polyline` from `list[tuple[float, float]]` to NumPy in
  the first prototype.  That is a larger graph-model change with wider API
  impact.
- Do not round or quantize JSON/Lanelet2 output as a hidden compatibility fix.
  If output canonicalization is needed, make it an explicit later decision.

## Current dtype flow

The relevant data path is:

```text
load_trajectory_csv()
  -> Trajectory.timestamps: np.float64, shape (n,)
  -> Trajectory.xy: np.float64, shape (n, 2)
  -> Trajectory.z: np.float64 | None, shape (n,)

build_graph_from_trajectory()
  -> trajectory_to_polylines()
  -> centerline_from_points()
  -> polylines_to_graph()
  -> Graph.nodes[].position: tuple[float, float]
  -> Graph.edges[].polyline: list[tuple[float, float]]

export_map_bundle()
  -> sim/road_graph.json from Graph.to_dict()
  -> sim/map.geojson from graph + traj.xy
  -> lanelet/map.osm from graph
  -> nav/sd_nav.json lengths from graph edge polylines
```

Important files:

- `roadgraph_builder/io/trajectory/loader.py`: loader fixes `timestamps`, `xy`,
  and optional `z` to `np.float64`.
- `roadgraph_builder/pipeline/build_graph.py`: centerline construction,
  splitting, endpoint merging, duplicate merging, and optional 3D annotation
  all consume `traj.xy`.
- `roadgraph_builder/core/graph/{node.py,edge.py,graph.py}`: graph geometry is
  stored as Python floats and serialized directly.
- `roadgraph_builder/io/export/{json_exporter.py,geojson.py,bundle.py}`:
  exporters do not canonicalize coordinates; the current float text is whatever
  Python's JSON writer emits.
- `roadgraph_builder/cli/main.py` and `roadgraph_builder/cli/dataset.py`:
  `build`, `visualize`, `export-bundle`, and `process-dataset` all load
  trajectory CSVs through the same loader.

## Compatibility constraints

The codebase repeatedly treats omitted feature flags as byte-identical paths.
For this optimization, a default float32 loader would likely change graph
coordinates and derived exports.  The schema accepts floats, but byte identity
and practical routing/map-matching drift are separate concerns.

The current release-bundle tests validate shape and schemas for
`examples/frozen_bundle/`, plus an opt-in shell-out rebuild guarded by
`ROADGRAPH_RUN_RELEASE_TEST=1`.  They do not provide an always-on byte-for-byte
comparison of every generated bundle file.  Add explicit drift checks before
making any default dtype change.

## Options

### A. Loader-level dtype option, default float64

Add an opt-in coordinate dtype to:

```python
load_trajectory_csv(path, *, load_z=False, xy_dtype=np.float64)
load_multi_trajectory_csvs(paths, *, load_z=False, xy_dtype=np.float64)
```

Keep timestamps and z as float64.  This gives callers a measured memory-saving
path with zero default behavior change.

Pros:

- Smallest patch.
- Easy unit tests: default dtype remains float64; opt-in returns float32.
- Lets memory profile compare only the trajectory coordinate array first.

Cons:

- `build_graph_from_csv()` would need a way to pass the dtype if the CLI should
  exercise it.
- Output drift still exists when callers opt in.

### B. BuildParams/CLI opt-in, default float64

Add a string field such as:

```python
BuildParams.trajectory_xy_dtype: str = "float64"
```

Then thread it through:

- `build_graph_from_csv()` -> `load_trajectory_csv(..., xy_dtype=...)`
- CLI parser -> `--trajectory-dtype {float64,float32}`
- `build`, `visualize`, `export-bundle`, and `process-dataset`

Recommended first implementation if the optimization should be user-visible in
v0.8.  Keep the default `float64`.

Pros:

- End-to-end memory measurement is possible through real commands.
- Default output remains unchanged.
- The flag clearly communicates that output may drift.

Cons:

- Touches more CLI surface and completions.
- Needs careful tests across build/export-bundle/multi-CSV.

### C. Internal build-only downcast

Keep loader float64, then copy `traj.xy.astype(np.float32)` inside
`build_graph_from_trajectory()`.

Not recommended.  It can reduce downstream temporary memory, but it first loads
float64 and then allocates float32, so peak RSS can get worse for large CSVs.
It also makes output drift less obvious to callers.

### D. Float32 default

Change `load_trajectory_csv()` so `Trajectory.xy` defaults to float32.

Not recommended now.  This is the biggest memory win on paper, but it changes
default graph geometry, bundle outputs, route lengths, and map GeoJSON
coordinates.  It should only be considered after opt-in drift numbers are
recorded on real datasets.

### E. Quantized export canonicalization

Round graph/GeoJSON/Lanelet2 coordinates to a fixed precision before export.

Defer.  It could make float32 output more stable, but it changes the output
contract even for float64.  Treat it as a separate compatibility proposal.

## Recommended path

Phase 0 is complete with this memo.

Phase 1 is complete: option B landed as opt-in only:

- Add `xy_dtype` support to trajectory loading, defaulting to float64.
- Add `BuildParams.trajectory_xy_dtype = "float64"` or equivalent.
- Add CLI `--trajectory-dtype {float64,float32}` for trajectory CSV commands.
- Add `scripts/profile_memory.py --trajectory-dtype {float64,float32}` for
  side-by-side memory reports.
- Keep timestamps and z float64.
- Preserve all current default outputs.

Phase 2 should measure and document drift:

Phase 2 is complete for the current opt-in prototype:

- `docs/float32_drift_report.md` records Paris 800-row and Berlin 7,500-row
  float64/float32 comparisons.
- `scripts/compare_float32_drift.py` rebuilds float64 / float32 bundles and
  compares `road_graph.json`, `sd_nav.json`, `map.geojson`, and Lanelet2 OSM
  topology plus coordinate drift, with JSON/Markdown output and optional
  failure thresholds.
- A `/tmp`-only 1M-row synthetic memory profile shows the direct retained
  `Trajectory.xy` allocation drop is real (24,000,568 B -> 16,000,568 B) and
  tracemalloc peak drops by about 19 MB, but full `export-bundle` process RSS
  only drops by about 2.6 MB because build/export temporaries dominate.
- A `/tmp` OSM public-trace replay check shows the same pattern: 500k load-only
  `Trajectory.xy` drops 8,000,000 B -> 4,000,000 B, but 75k full export RSS
  only drops about 4.0 MB. The 75k replay also showed edge/Lanelet ID drift
  under float32, so it should be treated as a stress warning rather than
  evidence for a default flip.
- Topology was unchanged on the Paris and Berlin release-quality samples.
- Max observed graph / GeoJSON / Lanelet coordinate drift on those samples was
  below 1 mm.
- `Trajectory.xy` allocation dropped as expected, but process RSS still did
  not show a reliable enough full-pipeline win to justify changing the default.

Still open: only reconsider the default if a real-world workload shows a
meaningful full-pipeline RSS win and passes a strict topology / ID stability
gate.

Phase 3 should decide whether float32 can become default:

- Only consider a default flip if node/edge counts stay identical, route
  lengths remain inside the accepted tolerance, and output-diff messaging is
  acceptable for the next version.
- If the default flips, document it as a behavior-affecting change.

## Byte-identity impact matrix

| Area | Float32 risk | Recommendation |
| --- | --- | --- |
| `Trajectory.timestamps` | Low memory benefit, timing sort sensitivity if changed | Keep float64 |
| `Trajectory.xy` | Main memory win; changes centerlines and exported coordinate text | Opt-in float32 first |
| `Trajectory.z` | 3D slope/elevation output may drift | Keep float64 |
| `Graph.nodes[].position` | Derived from `xy`; JSON coordinate text may change | Do not store as NumPy in prototype |
| `Edge.polyline` | Derived from `xy`; affects JSON, GeoJSON, Lanelet2, routing | Measure drift before default change |
| `sim/map.geojson` trajectory feature | Directly serializes `traj.xy` | Expected to differ when opt-in |
| `nav/sd_nav.json` | Edge lengths may change slightly | Tolerance test needed |
| `lanelet/map.osm` | Lat/lon conversion from graph geometry may change | Tolerance or byte diff report |
| OSM highway graph path | Independent of trajectory loader | No change |
| LiDAR/camera code | Separate dtype-sensitive math | Out of scope |

## Tests for prototype

Run existing focused tests:

```bash
python3 -m pytest \
  tests/test_loader.py \
  tests/test_multi_csv.py \
  tests/test_pipeline.py \
  tests/test_graph_json.py \
  tests/test_bundle_export.py \
  tests/test_release_bundle.py \
  tests/test_svg_export.py \
  tests/test_cli_end_to_end.py
```

Add new tests:

- Loader default returns float64 for `timestamps`, `xy`, and `z`.
- Loader opt-in returns float32 for `xy` only.
- Multi-CSV preserves opt-in dtype and primary-first ordering.
- Default `build` or `export-bundle` output is byte-identical before/after the
  patch for a small fixture.
- Opt-in float32 keeps node count and edge count equal on the sample trajectory.
- Opt-in float32 route or graph-length drift stays under an explicit tolerance.

For an end-to-end memory run, use the profiler after it accepts the opt-in
dtype:

```bash
python3 scripts/profile_memory.py examples/osm_public_trackpoints.csv /tmp/profile_float64 \
  --output-json /tmp/profile_float64.json --output-md /tmp/profile_float64.md

python3 scripts/profile_memory.py examples/osm_public_trackpoints.csv /tmp/profile_float32 \
  --trajectory-dtype float32 \
  --output-json /tmp/profile_float32.json --output-md /tmp/profile_float32.md
```

## Open decisions

- Acceptable coordinate drift for trajectory-derived graph output:
  recommend starting with `<= 0.05 m` max XY drift for graph vertices and
  `<= 0.1%` route-length drift, then adjust after real-data numbers.
- Whether `--trajectory-dtype float32` should be public in v0.8 or hidden
  behind library/profile code until drift is better characterized.
- Which city-scale dataset should be the memory target.  Paris public GPS is
  convenient, but a larger `/tmp` dataset may be needed to make RSS savings
  obvious.
