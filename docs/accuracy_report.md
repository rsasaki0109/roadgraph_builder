# Lane-count accuracy report — roadgraph_builder v0.7.0

Compares `infer-lane-count` predictions against OSM `lanes=` ground truth for
three city bboxes. OSM `lanes=` values are community-entered and may contain
errors, so this is a **relative baseline** — not a surveyed truth.

## Method

1. Fetch OSM highway ways for the bbox with `scripts/fetch_osm_highways.py`.
2. Build a graph: `roadgraph_builder build-osm-graph raw.json graph.json --origin-lat ... --origin-lon ...`
3. Infer lane counts: `roadgraph_builder infer-lane-count graph.json graph_lc.json`
4. Run `scripts/measure_lane_accuracy.py --graph graph_lc.json --osm-lanes-json raw.json --output result.json`

Default script matching criterion: edge centroid within **5 m** of OSM way
centroid + tangent alignment cosine ≥ 0.7.

When the graph JSON contains `metadata.map_origin` (written by
`build-osm-graph` with an origin), `measure_lane_accuracy.py` automatically
converts OSM node lon/lat into the same local meter frame before comparing.
Raw OSM coords are treated as degrees only when no `map_origin` is present
(e.g. synthetic test fixtures).

Paris 20e, Tokyo Ginza, and Berlin Mitte below are canonical runs at
`--matching-tolerance-m 20`: tight tolerances (≤ 10 m) under-match because
`build-osm-graph` splits every OSM way at every junction, so a single way
becomes N graph edges whose centroids drift away from the way-level
centroid. 20 m balances match-rate against cross-street leakage on dense
urban grids.

---

## 1. Paris 20e arrondissement

**Bbox:** `2.3900,48.8450,2.4120,48.8620` (roughly 20e arr., ~2 km × 1.9 km)

### Fetch recipe

```bash
python scripts/fetch_osm_highways.py \
    --bbox 2.3900,48.8450,2.4120,48.8620 \
    --output /tmp/paris_20e_raw.json

roadgraph_builder build-osm-graph /tmp/paris_20e_raw.json \
    /tmp/paris_20e_graph.json \
    --origin-lat 48.8535 --origin-lon 2.4010

roadgraph_builder infer-lane-count \
    /tmp/paris_20e_graph.json /tmp/paris_20e_lc.json

python scripts/measure_lane_accuracy.py \
    --graph /tmp/paris_20e_lc.json \
    --osm-lanes-json /tmp/paris_20e_raw.json \
    --matching-tolerance-m 20.0 \
    --output /tmp/paris_20e_accuracy.json
```

### Results

Measured 2026-04-21 against Overpass snapshot for bbox
`2.3900,48.8450,2.4120,48.8620` (794 ways, 3471 nodes; 245 ways carry
`lanes=`). `build-osm-graph` produced a 795-node / 997-edge graph;
`infer-lane-count` used the `default` source (no LiDAR markings, no
`trace_stats`) so all 997 edges predict `lane_count = 1`.

At `--matching-tolerance-m 20`: **193 / 997 edges matched** (804
unmatched), **MAE = 0.938 lanes**.

| Actual (OSM) | Predicted 1 | Predicted 2+ |
| ------------ | ----------- | ------------ |
| 1            | 56          | —            |
| 2            | 105         | —            |
| 3            | 20          | —            |
| 4            | 12          | —            |

Tightening to 5 m matches 110 edges (MAE 1.136); 10 m matches 148 edges
(MAE 1.020). Loosening to 50 m matches 318/997 edges (MAE 0.890).
As in Tokyo and Berlin, this is the always-predict-1 baseline; lane
markings or trajectory fan-out are needed for a real lane-count signal.

---

## 2. Tokyo Ginza

**Bbox:** `139.7600,35.6680,139.7750,35.6750`

### Fetch recipe

```bash
python scripts/fetch_osm_highways.py \
    --bbox 139.7600,35.6680,139.7750,35.6750 \
    --output /tmp/tokyo_ginza_raw.json

roadgraph_builder build-osm-graph /tmp/tokyo_ginza_raw.json \
    /tmp/tokyo_ginza_graph.json \
    --origin-lat 35.6700 --origin-lon 139.7680

roadgraph_builder infer-lane-count \
    /tmp/tokyo_ginza_graph.json /tmp/tokyo_ginza_lc.json

python scripts/measure_lane_accuracy.py \
    --graph /tmp/tokyo_ginza_lc.json \
    --osm-lanes-json /tmp/tokyo_ginza_raw.json \
    --matching-tolerance-m 20.0 \
    --output /tmp/tokyo_ginza_accuracy.json
```

### Results

Measured 2026-04-20 against Overpass snapshot for bbox
`139.7600,35.6680,139.7750,35.6750` (415 ways, 1891 nodes; 122 ways carry
`lanes=`).  `build-osm-graph` produced a 395-node / 598-edge graph;
`infer-lane-count` used the `default` source (no LiDAR markings, no
`trace_stats`) so all 598 edges predict `lane_count = 1`.

At `--matching-tolerance-m 20`: **113 / 598 edges matched** (485
unmatched — most residential ways in Ginza carry no `lanes=` tag), **MAE
= 0.903 lanes**.

| Actual (OSM) | Predicted 1 | Predicted 2+ |
| ------------ | ----------- | ------------ |
| 1            | 42          | —            |
| 2            | 44          | —            |
| 3            | 23          | —            |
| 4            | 4           | —            |

Tightening to 5 m matches only 32 edges (MAE 0.875).  Loosening to 200 m
matches 542/598 edges (MAE 0.721) — still always-predict-1 baseline, but
less biased toward arterial subset.  Real `infer-lane-count` with
`--lane-markings-json` from LiDAR would break the 1-only prediction.

---

## 3. Berlin Mitte

**Bbox:** `13.3700,52.5100,13.4000,52.5250`

### Fetch recipe

```bash
python scripts/fetch_osm_highways.py \
    --bbox 13.3700,52.5100,13.4000,52.5250 \
    --output /tmp/berlin_mitte_raw.json

roadgraph_builder build-osm-graph /tmp/berlin_mitte_raw.json \
    /tmp/berlin_mitte_graph.json \
    --origin-lat 52.5175 --origin-lon 13.3850

roadgraph_builder infer-lane-count \
    /tmp/berlin_mitte_graph.json /tmp/berlin_mitte_lc.json

python scripts/measure_lane_accuracy.py \
    --graph /tmp/berlin_mitte_lc.json \
    --osm-lanes-json /tmp/berlin_mitte_raw.json \
    --matching-tolerance-m 20.0 \
    --output /tmp/berlin_mitte_accuracy.json
```

### Results

Measured 2026-04-20 against Overpass snapshot for bbox
`13.3700,52.5100,13.4000,52.5250` (1659 ways, 4748 nodes; 566 ways carry
`lanes=`, up to `lanes=5`). `build-osm-graph` produced a 1423-node /
1640-edge graph; `infer-lane-count` used the `default` source (all edges
predict `lane_count = 1`).

At `--matching-tolerance-m 20`: **531 / 1640 edges matched** (1109
unmatched), **MAE = 1.220 lanes**.

| Actual (OSM) | Predicted 1 | Predicted 2+ |
| ------------ | ----------- | ------------ |
| 1            | 59          | —            |
| 2            | 359         | —            |
| 3            | 63          | —            |
| 4            | 37          | —            |
| 5            | 13          | —            |

Berlin Mitte arterials skew toward `lanes=2` (68% of matched pairs) so
always-predict-1 yields MAE ≈ 1.2 — a noticeably worse baseline than
Ginza because the distribution has less mass at 1.  Again, this is a
baseline against the bare skeleton; supplying lane markings or
trajectory fan-out would shrink the error.

---

## Interpretation notes

- `infer-lane-count` without lane markings (`source=default`) always predicts
  `lane_count=1`. Real accuracy requires LiDAR lane markings or `trace_stats`
  perpendicular offsets from multi-pass trajectories.
- OSM `lanes=` may count one direction only (`lanes:forward` / `lanes:backward`
  exist for divided roads). The matcher uses the raw `lanes=` value; this can
  cause apparent over-prediction on divided arterials.
- Matching tolerance of 5 m works well for dense urban grids; increase to 10 m
  for sparse motorway networks with wide medians.
