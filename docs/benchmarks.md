# Performance Benchmarks

Baseline wall-clock times recorded at v0.5.0 (commit anchored on v0.4.0 state,
measured with `python scripts/run_benchmarks.py --no-warmup`).

## Machine

- OS: Linux 6.14.0-36-generic (Ubuntu)
- CPU: (development workstation)
- Python: 3.12 (CPython)

## v0.5.0 baseline (2026-04-19)

| Benchmark | elapsed (s) | Notes |
|---|---|---|
| `polylines_to_graph_paris` | 0.167 | OSM public-trackpoints CSV, `--max-step-m 40 --merge-endpoint-m 8` |
| `polylines_to_graph_10k_synth` | 1.371 | 10×10 grid, 2 200-point synthetic trajectory, `--max-step-m 60` |
| `shortest_path_paris` | 0.034 | 100 Dijkstra queries on the Paris graph |
| `export_bundle_end_to_end` | 0.029 | Full export-bundle pipeline on sample trajectory |

## v0.7.0-dev P1 (2026-04-19) — fast crossing splitters

`polylines_to_graph_10k_synth` restored to a 50×50 grid (~25 000 points).
The O(N²) path would have taken ~314 s at this size; the O(N log N) fast path
(uniform grid hash, `pipeline/crossing_splitters.py`) completes in ~21 s.

| Benchmark | elapsed (s) | Notes |
|---|---|---|
| `polylines_to_graph_paris` | 0.175 | Unchanged — Paris is small; byte-identical result |
| `polylines_to_graph_10k_synth` | 21.45 | **50×50 grid**, ~25 000 pts, fast splitter (P1) |
| `shortest_path_paris` | 0.014 | Unchanged |
| `export_bundle_end_to_end` | 0.016 | Unchanged |

Note: the 21 s includes `merge_near_parallel_edges` and
`consolidate_clustered_junctions` (still O(N²) over edges, not targeted in
P1). The crossing/T-junction splitters themselves take < 0.5 s for this size.

## v0.7.2-dev routing hot path (2026-04-21)

`shortest_path` now caches base edge lengths / adjacency per `Graph` and uses
a node-level Dijkstra fast path when no turn restrictions or lane-level routing
are requested. Turn-restricted routing still uses the directed incoming-edge
state machine.

One-off 55×55 grid, 120 source/destination pairs, same Python process:

| Version | Pass 1 | Pass 2 | Pass 3 | Notes |
|---|---:|---:|---:|---|
| before | 7.002 s | 6.459 s | n/a | Rebuilt adjacency and ran directed-state Dijkstra for every query |
| after | 2.699 s | 2.259 s | 1.900 s | Cached base topology plus node-level no-restriction Dijkstra |

The benchmark suite now includes `shortest_path_grid_120`. On this workstation,
`python scripts/run_benchmarks.py --no-warmup` measured:

| Benchmark | elapsed (s) | Notes |
|---|---:|---|
| `polylines_to_graph_paris` | 0.150 | OSM public-trackpoints CSV, small local fixture |
| `polylines_to_graph_10k_synth` | 56.071 | 50×50 grid, ~25 000 pts |
| `shortest_path_paris` | 0.031 | Existing small-graph routing smoke |
| `shortest_path_grid_120` | 1.940 | 120 routes on a 55×55 synthetic graph |
| `nearest_node_grid_2000` | 0.547 | 2000 snaps on a 300×300 node grid |
| `export_bundle_end_to_end` | 0.021 | Full export-bundle pipeline on sample trajectory |

## v0.7.2-dev nearest-node spatial index (2026-04-21)

`nearest_node` now caches graph nodes into spatial hash cells. Queries check
nearby cells exactly and use cell-boundary lower bounds for far-out queries.

One-off 300×300 node grid, 2000 xy queries:

| Version | Pass 1 | Pass 2 | Pass 3 | Notes |
|---|---:|---:|---:|---|
| before | 59.317 s | 53.563 s | n/a | Python full scan over all 90 000 nodes per query |
| vector-cache prototype | 2.596 s | 0.931 s | 0.924 s | Cached arrays but still O(N) per query |
| spatial index | 0.626 s | 0.566 s | 0.594 s | Cached spatial cells with exact local distance checks |

## v0.7.2-dev build graph spatial indexes (2026-04-22)

The large synthetic graph build was still dominated by local geometry passes:
endpoint union-find scanned every endpoint pair, near-parallel edge merging
scanned every edge pair before applying its endpoint distance-sum rule, and the
T-junction pass indexed expanded whole-polyline boxes before projecting each
candidate endpoint onto the full polyline. These now use spatial candidate
indexes while preserving the old merge/projection predicates.

One-off 50x50 grid, ~25 000 trajectory points:

| Version | Pass 1 | Pass 2 | Pass 3 | Notes |
|---|---:|---:|---:|---|
| before | 42.476 s | 46.185 s | 46.087 s | Endpoint union-find + near-parallel edge pair scans were quadratic |
| endpoint + near-parallel indexes | 1.723 s | 1.318 s | 1.255 s | Endpoint and near-parallel scans use spatial candidate indexes |
| plus T-junction segment index | 1.009 s | 0.523 s | 0.544 s | T-junction queries project only nearby candidate segments |
| plus lean near-parallel loop | 0.912 s | 0.732 s | 0.699 s | Reuses endpoint arrays and avoids sorted candidate/set-pair hot-loop work |

After these changes, `python scripts/run_benchmarks.py --no-warmup` measured:

| Benchmark | elapsed (s) | Notes |
|---|---:|---|
| `polylines_to_graph_paris` | 0.148 | OSM public-trackpoints CSV, small local fixture |
| `polylines_to_graph_10k_synth` | 0.471 | 50x50 grid, ~25 000 pts |
| `shortest_path_paris` | 0.019 | Existing small-graph routing smoke |
| `shortest_path_grid_120` | 1.679 | 120 routes on a 55x55 synthetic graph |
| `nearest_node_grid_2000` | 0.390 | 2000 snaps on a 300x300 node grid |
| `export_bundle_end_to_end` | 0.018 | Full export-bundle pipeline on sample trajectory |

## v0.7.2-dev GeoJSON and bundle JSON compact paths (2026-04-22)

Large `map.geojson` writes were dominated by repeated meter-to-WGS84 conversion
setup and pretty JSON serialization. The exporter now precomputes conversion
constants once per map, and adds an opt-in compact writer for large bundle
exports. Default output stays pretty-printed and is still covered by the frozen
release bundle byte gate.

One-off 180x180 grid, 32,400 nodes, 64,440 edges, 96,840 GeoJSON features:

| Export path | Before | After | Output size | Notes |
|---|---:|---:|---:|---|
| `build_map_geojson` | 1.417 s | 0.695 s | n/a | Coordinate conversion constants reused per map |
| default pretty `export_map_geojson` | 7.030 s | 3.052 s | 42.8 MB | Same parsed document and pretty output semantics |
| compact `export_map_geojson(compact=True)` | n/a | 1.760 s | 23.6 MB | Same parsed document without indentation |

The same default-preserving compact writer is now available for non-GeoJSON
bundle JSON (`nav/sd_nav.json`, `sim/road_graph.json`, and `manifest.json`).
On the same 180x180 grid, using prebuilt writer-shaped documents:

| JSON document | Pretty | Compact | Pretty size | Compact size | Notes |
|---|---:|---:|---:|---:|---|
| `sim/road_graph.json` | 1.593 s | 0.431 s | 21.3 MB | 10.5 MB | `export_graph_json(compact=True)` |
| `nav/sd_nav.json` | 0.654 s | 0.151 s | 17.0 MB | 11.6 MB | Same parsed document, compact separators |
| `manifest.json` | <0.001 s | <0.001 s | <0.01 MB | <0.01 MB | Included for bundle consistency |

The benchmark suite now includes `export_geojson_grid_120_compact` and
`export_bundle_json_grid_120_compact`. On this workstation,
`python scripts/run_benchmarks.py --no-warmup` measured:

| Benchmark | elapsed (s) | Notes |
|---|---:|---|
| `polylines_to_graph_paris` | 0.122 | OSM public-trackpoints CSV, small local fixture |
| `polylines_to_graph_10k_synth` | 0.445 | 50x50 grid, ~25 000 pts |
| `shortest_path_paris` | 0.018 | Existing small-graph routing smoke |
| `shortest_path_grid_120` | 1.646 | 120 routes on a 55x55 synthetic graph |
| `nearest_node_grid_2000` | 0.404 | 2000 snaps on a 300x300 node grid |
| `export_geojson_grid_120_compact` | 0.601 | Compact GeoJSON export on a 120x120 grid |
| `export_bundle_json_grid_120_compact` | 0.421 | Compact road_graph/sd_nav/manifest JSON on a 120x120 grid |
| `export_bundle_end_to_end` | 0.004 | Full export-bundle pipeline on sample trajectory |

## Regression policy

CI comparison mode (`--baseline baseline.json`) fails with exit code 1 if any
benchmark regresses by more than 200 % (i.e. runs 3× slower than baseline).

## Running

```bash
# One-shot
make bench

# Compare against saved baseline
python scripts/run_benchmarks.py --baseline docs/baseline.json
```
