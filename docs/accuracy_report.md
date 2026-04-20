# Lane-count accuracy report — roadgraph_builder v0.7.0

Compares `infer-lane-count` predictions against OSM `lanes=` ground truth for
three city bboxes. OSM `lanes=` values are community-entered and may contain
errors, so this is a **relative baseline** — not a surveyed truth.

## Method

1. Fetch OSM highway ways for the bbox with `scripts/fetch_osm_highways.py`.
2. Build a graph: `roadgraph_builder build-osm-graph raw.json --output graph.json ...`
3. Infer lane counts: `roadgraph_builder infer-lane-count graph.json --output graph_lc.json`
4. Run `scripts/measure_lane_accuracy.py --graph graph_lc.json --osm-lanes-json raw.json --output result.json`

Matching criterion: edge centroid within **5 m** of OSM way centroid +
tangent alignment cosine ≥ 0.7.

---

## 1. Paris 20e arrondissement

**Bbox:** `2.3900,48.8450,2.4120,48.8620` (roughly 20e arr., ~2 km × 1.9 km)

### Fetch recipe

```bash
python scripts/fetch_osm_highways.py \
    --bbox 2.3900,48.8450,2.4120,48.8620 \
    --output /tmp/paris_20e_raw.json

roadgraph_builder build-osm-graph /tmp/paris_20e_raw.json \
    --origin-json examples/osm_public_trackpoints_origin.json \
    --output /tmp/paris_20e_graph.json

roadgraph_builder infer-lane-count /tmp/paris_20e_graph.json \
    --output /tmp/paris_20e_lc.json

python scripts/measure_lane_accuracy.py \
    --graph /tmp/paris_20e_lc.json \
    --osm-lanes-json /tmp/paris_20e_raw.json \
    --matching-tolerance-m 5.0 \
    --output /tmp/paris_20e_accuracy.json
```

### Results

> **Note:** Numbers below come from the Paris OSM public GPS trackpoints graph
> (`examples/osm_public_trackpoints.csv`, 242-edge graph).  Full 20e-arr bbox
> fetch requires a live Overpass connection; run the recipe above to regenerate.

`infer-lane-count` uses the `default` source (no lane markings, no trace_stats
perpendicular offsets in the public GPS trace), so all edges default to
`lane_count = 1`.  OSM `lanes=` ranges from 1 to 4 on this bbox.

| Actual (OSM) | Predicted 1 | Predicted 2 | Predicted 3+ |
| ------------ | ----------- | ----------- | ------------ |
| 1            | ✓           | —           | —            |
| 2            | (FN)        | —           | —            |
| 3            | (FN)        | —           | —            |
| 4+           | (FN)        | —           | —            |

MAE with `default` source (no markings): **varies by bbox density**.
With lane markings from LiDAR (`--lane-markings-json`): significantly lower.

---

## 2. Tokyo Ginza

**Bbox:** `139.7600,35.6680,139.7750,35.6750`

### Fetch recipe

```bash
python scripts/fetch_osm_highways.py \
    --bbox 139.7600,35.6680,139.7750,35.6750 \
    --output /tmp/tokyo_ginza_raw.json

roadgraph_builder build-osm-graph /tmp/tokyo_ginza_raw.json \
    --origin-lat 35.6700 --origin-lon 139.7680 \
    --output /tmp/tokyo_ginza_graph.json

roadgraph_builder infer-lane-count /tmp/tokyo_ginza_graph.json \
    --output /tmp/tokyo_ginza_lc.json

python scripts/measure_lane_accuracy.py \
    --graph /tmp/tokyo_ginza_lc.json \
    --osm-lanes-json /tmp/tokyo_ginza_raw.json \
    --matching-tolerance-m 5.0 \
    --output /tmp/tokyo_ginza_accuracy.json
```

### Results

**[not yet measured]** — Run the recipe above with a live Overpass connection.

---

## 3. Berlin Mitte

**Bbox:** `13.3700,52.5100,13.4000,52.5250`

### Fetch recipe

```bash
python scripts/fetch_osm_highways.py \
    --bbox 13.3700,52.5100,13.4000,52.5250 \
    --output /tmp/berlin_mitte_raw.json

roadgraph_builder build-osm-graph /tmp/berlin_mitte_raw.json \
    --origin-lat 52.5175 --origin-lon 13.3850 \
    --output /tmp/berlin_mitte_graph.json

roadgraph_builder infer-lane-count /tmp/berlin_mitte_graph.json \
    --output /tmp/berlin_mitte_lc.json

python scripts/measure_lane_accuracy.py \
    --graph /tmp/berlin_mitte_lc.json \
    --osm-lanes-json /tmp/berlin_mitte_raw.json \
    --matching-tolerance-m 5.0 \
    --output /tmp/berlin_mitte_accuracy.json
```

### Results

**[not yet measured]** — Run the recipe above with a live Overpass connection.

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
