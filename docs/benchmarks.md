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
