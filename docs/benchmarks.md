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
| `polylines_to_graph_paris` | 0.181 | OSM public-trackpoints CSV, small local fixture |
| `polylines_to_graph_10k_synth` | 42.656 | 50×50 grid, ~25 000 pts |
| `shortest_path_paris` | 0.030 | Existing small-graph routing smoke |
| `shortest_path_grid_120` | 1.320 | 120 routes on a 55×55 synthetic graph |
| `export_bundle_end_to_end` | 0.024 | Full export-bundle pipeline on sample trajectory |

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
