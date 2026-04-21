# Float32 trajectory drift report

Measured: 2026-04-21

Status: opt-in float32 is safe enough for experiments, but **not enough reason
to flip the default**.  Keep default trajectory loading at float64 until a
larger real-world memory target shows meaningful RSS reduction.

## What Was Measured

Two datasets were run through `scripts/profile_memory.py` twice: once with
`--trajectory-dtype float64` and once with `--trajectory-dtype float32`.

Datasets:

- `examples/osm_public_trackpoints.csv`: committed Paris OSM public GPS sample,
  800 data rows, 30 KB.
- `/tmp/osm_tune_berlin/berlin_mitte_trackpoints.csv`: Berlin Mitte tuning
  sample, 7,500 data rows, 291 KB.  Raw CSV remains in `/tmp` and is not
  committed.

Commands:

```bash
python3 scripts/profile_memory.py examples/osm_public_trackpoints.csv /tmp/profile_float64 \
  --trajectory-dtype float64 \
  --output-json /tmp/profile_float64.json \
  --output-md /tmp/profile_float64.md

python3 scripts/profile_memory.py examples/osm_public_trackpoints.csv /tmp/profile_float32 \
  --trajectory-dtype float32 \
  --output-json /tmp/profile_float32.json \
  --output-md /tmp/profile_float32.md

python3 scripts/profile_memory.py /tmp/osm_tune_berlin/berlin_mitte_trackpoints.csv \
  /tmp/profile_berlin_float64 \
  --trajectory-dtype float64 --origin-lat 52.5175 --origin-lon 13.385 \
  --output-json /tmp/profile_berlin_float64.json \
  --output-md /tmp/profile_berlin_float64.md

python3 scripts/profile_memory.py /tmp/osm_tune_berlin/berlin_mitte_trackpoints.csv \
  /tmp/profile_berlin_float32 \
  --trajectory-dtype float32 --origin-lat 52.5175 --origin-lon 13.385 \
  --output-json /tmp/profile_berlin_float32.json \
  --output-md /tmp/profile_berlin_float32.md
```

The bundle comparison is now reproducible without ad-hoc parsing:

```bash
python3 scripts/compare_float32_drift.py examples/osm_public_trackpoints.csv \
  /tmp/rg_float32_drift_compare \
  --overwrite \
  --output-json /tmp/rg_float32_drift_compare.json \
  --output-md /tmp/rg_float32_drift_compare.md \
  --max-coordinate-drift-m 0.01 \
  --fail-on-topology-change
```

On the committed Paris sample this reports unchanged topology and max
coordinate drift **0.000141 m**, matching the original one-off measurement.

The generated bundles were compared by parsing:

- `sim/road_graph.json`
- `nav/sd_nav.json`
- `sim/map.geojson`
- `lanelet/map.osm`

`sim/trajectory.csv` is copied from input and stayed byte-identical.

## Memory Results

`ru_maxrss` is a process high-water mark.  On these small inputs, Python import
and module setup dominate, so RSS is noisy and not a clean measure of the
coordinate-array saving.  `tracemalloc` and the loader allocation line show the
expected reduction more directly.

| Dataset | dtype | peak RSS after export | tracemalloc peak |
| --- | ---: | ---: | ---: |
| Paris 800 rows | float64 | 87,300 KB | 8,019 KB |
| Paris 800 rows | float32 | 87,164 KB | 8,013 KB |
| Paris delta | float32 - float64 | -136 KB | -6 KB |
| Berlin 7,500 rows | float64 | 88,272 KB | 13,543 KB |
| Berlin 7,500 rows | float32 | 89,032 KB | 13,486 KB |
| Berlin delta | float32 - float64 | +760 KB | -57 KB |

For Berlin, the top-allocation table showed
`roadgraph_builder/io/trajectory/loader.py:104` dropping from **180,568 B** to
**120,568 B**.  That 60,000 B reduction exactly matches 7,500 rows x 2 XY
coordinates x 4 saved bytes per coordinate.

Conclusion: the opt-in path works, but for current public samples the absolute
memory win is too small to justify a default-output change.

## Output Drift

### Paris 800-row Sample

| Metric | float64 | float32 | Delta / drift |
| --- | ---: | ---: | ---: |
| Graph nodes | 9 | 9 | 0 |
| Graph edges | 5 | 5 | 0 |
| Edge vertex count mismatches | 0 | 0 | 0 |
| Max node XY drift | - | - | 0.000037 m |
| Max edge-vertex XY drift | - | - | 0.000138 m |
| Mean edge-vertex XY drift | - | - | 0.000022 m |
| Total edge length | 874.645621763 m | 874.645621983 m | +0.000000220 m |
| Max per-edge length drift | - | - | 0.000055 m |
| Max GeoJSON coordinate drift | - | - | 0.000141 m |
| Lanelet OSM nodes / ways / relations | 283 / 15 / 6 | 283 / 15 / 6 | unchanged |
| Max Lanelet node drift | - | - | 0.000140 m |

### Berlin 7,500-row Sample

| Metric | float64 | float32 | Delta / drift |
| --- | ---: | ---: | ---: |
| Graph nodes | 65 | 65 | 0 |
| Graph edges | 64 | 64 | 0 |
| Edge vertex count mismatches | 0 | 0 | 0 |
| Max node XY drift | - | - | 0.000189 m |
| Max edge-vertex XY drift | - | - | 0.000723 m |
| Mean edge-vertex XY drift | - | - | 0.000056 m |
| Total edge length drift | - | - | +0.000230 m |
| Total edge length drift (%) | - | - | +0.000002 % |
| Max per-edge length drift | - | - | 0.000237 m |
| Max GeoJSON coordinate drift | - | - | 0.000723 m |
| Lanelet OSM nodes / ways / relations | 1,651 / 192 / 91 | 1,651 / 192 / 91 | unchanged |
| Max Lanelet node drift | - | - | 0.000723 m |

All non-trajectory output files differed byte-for-byte, as expected, because
coordinate text changes.  Topology and derived lengths stayed effectively
unchanged on both samples.  The largest observed geometric drift was below
1 mm.

## Decision

Keep `float64` as the default.

Recommended next state:

- Keep `--trajectory-dtype float32` as an opt-in profiling / large-dataset
  knob.
- Do not canonicalize exported coordinates just to hide float32 text drift.
- Do not flip the default until a larger city-scale workload demonstrates a
  meaningful process-level memory reduction.
- If float32 becomes user-facing in a release note, document that exported
  coordinate text is expected to differ while topology should remain stable.

## Follow-up Test Ideas

- Use `scripts/compare_float32_drift.py` as the reusable release-gate entry
  point when float32 measurements need to recur.
- Add an opt-in city-scale benchmark that asserts topology stability and
  sub-centimeter coordinate drift for `--trajectory-dtype float32`.
- Measure on a much larger trajectory input where `Trajectory.xy` is large
  enough to move process RSS instead of only `tracemalloc`.
