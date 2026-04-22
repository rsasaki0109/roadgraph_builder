# roadgraph_builder Showcase

`roadgraph_builder` is a graph-first map-building toolkit for people who need
road topology they can inspect, validate, route on, and export.

It starts from GPS trajectories or OSM highway ways, then keeps the result as a
plain graph: nodes, edges, centerline polylines, and optional attributes for
HD-lite geometry, semantics, routing, and provenance.

## 30 Second Pitch

- Build a road graph from trajectory CSV or OSM highway ways.
- Export the same graph to navigation JSON, simulation GeoJSON, and Lanelet2-style OSM.
- Route over the graph with turn restrictions, confidence filters, slope costs, lane-change costs, and reachability budgets.
- Add LiDAR / camera observations without making OpenCV, SciPy, or heavy geospatial stacks mandatory.
- Validate outputs with JSON Schemas and keep release artefacts stable with byte-for-byte sample bundle tests.

## What To Look At First

| Signal | Why it matters | Link |
| --- | --- | --- |
| Paris map preview | Real OSM-derived graph with turn restrictions, route overlay, and 500 m reachability overlay | [map](map.html) |
| Static route preview | Works in the GitHub README without running a server | [SVG](images/paris_grid_route.svg) |
| Architecture | One-page module map for build, routing, perception, export, schemas, and CLI | [architecture](ARCHITECTURE.md) |
| Benchmarks | Deterministic build / routing / reachability / export timings with a committed baseline | [benchmarks](benchmarks.md) |
| Accuracy report | Lane-count baseline against OSM `lanes=` in Paris / Tokyo / Berlin | [accuracy](accuracy_report.md) |

## Showcase Scenario: Paris OSM Grid

The committed Paris sample is built from OSM highway ways, not a hand-drawn
toy graph. It includes:

- 855 graph nodes and 1081 graph edges.
- 10 mapped OSM turn restrictions.
- A restriction-aware route from `n312` to `n191`.
- A 500 m service-area overlay from the same start node.
- ODbL attribution embedded in the committed assets.

The interesting bit is that route and reachability use the same policy layer:
turn restrictions, confidence filters, observed/unobserved weighting, and slope
costs are shared across shortest-path and service-area workflows.

## Core Workflows

### Build Once, Export Three Ways

```bash
roadgraph_builder export-bundle examples/sample_trajectory.csv ./out_bundle \
  --origin-json examples/toy_map_origin.json \
  --lane-width-m 3.5 \
  --detections-json examples/camera_detections_sample.json
```

Outputs:

- `nav/sd_nav.json` for navigation / routing seed data.
- `sim/road_graph.json` and `sim/map.geojson` for simulation and inspection.
- `lanelet/map.osm` for Lanelet2-style downstream tooling.
- `manifest.json` for provenance and graph statistics.

### Route With Real Constraints

```bash
roadgraph_builder route graph.json n0 n9 \
  --turn-restrictions-json turn_restrictions.json \
  --prefer-observed \
  --min-confidence 0.3 \
  --explain \
  --output route.geojson
```

The same routing layer supports safe A* acceleration, Dijkstra fallback,
slope-aware cost, lane-change routing, and prepared `RoutePlanner` instances
for repeated shortest-path queries. `--explain` adds route diagnostics such as
the selected engine, fallback reason, and queue work without changing the normal
route fields.

### Explore Reachability

```bash
roadgraph_builder reachable graph.json n0 \
  --max-cost-m 500 \
  --turn-restrictions-json turn_restrictions.json \
  --output reachable.geojson
```

The `ReachabilityAnalyzer` prepares topology, weighted adjacency, and policy
once for repeated service-area queries.

### Add Sensor Signals

```bash
roadgraph_builder fuse-lidar graph.json cloud.las fused.json --ground-plane
roadgraph_builder project-camera calib.json detections.json poses.json graph.json projected.json
roadgraph_builder apply-camera graph.json projected.json graph_with_semantics.json
```

These paths are deliberately modular: you can keep a pure-Python graph pipeline,
then opt into richer LiDAR / camera / HD-lite steps when data is available.

## Who This Is For

- Robotics and autonomy developers who need map-like graph artefacts without committing to a full HD map stack on day one.
- GIS and mobility engineers who want transparent JSON / GeoJSON outputs from trajectory or OSM-derived data.
- Simulation teams that need a repeatable road topology seed plus visual inspection assets.
- Researchers who want a small, hackable baseline for routing, map matching, lane inference, and sensor-fusion experiments.

## What This Is Not

This is not a cm-class survey HD map generator. It can export Lanelet2-style OSM
and carry HD-lite attributes, but production autonomy maps still require
calibrated sensors, validation, and domain-specific QA. The project is useful
because the intermediate graph is explicit, testable, and easy to extend.

## Measured Signals

- `shortest_path_grid_120`: 120 shortest-path queries on a 55x55 synthetic grid using one `RoutePlanner`; committed baseline `0.601 s`.
- `reachable_grid_120`: 120 service-area queries on the same grid using `ReachabilityAnalyzer`; committed baseline `0.270 s`.
- `nearest_node_grid_2000`: 2000 nearest-node snaps on a 300x300 node grid; committed baseline `0.432 s`.
- Full local test suite after the latest routing work: `611 passed, 28 skipped, 4 deselected`.

## Local Preview

```bash
cd docs
python3 -m http.server 8765
```

Open:

- `http://127.0.0.1:8765/` for the docs landing page.
- `http://127.0.0.1:8765/map.html` for the OSM basemap viewer.
