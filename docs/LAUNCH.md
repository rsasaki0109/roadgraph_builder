# Launch Notes

This file collects short public copy for announcing `roadgraph_builder` when the
repository is ready for wider visibility.

## One Line

`roadgraph_builder` builds inspectable road graphs from GPS trajectories, OSM,
LiDAR, and camera data, then exports navigation JSON, simulation GeoJSON, and
Lanelet2-style OSM with routing and validation.

## Short Post

I have been building `roadgraph_builder`, a Python toolkit for turning GPS
trajectories or OSM highway ways into a graph-first road map representation.

It keeps the map as nodes, edges, centerline polylines, and attributes, then
exports the same graph to navigation JSON, simulation GeoJSON, and
Lanelet2-style OSM. The routing layer supports turn restrictions, slope-aware
costs, lane-change costs, reachability, and repeated-query planners.

The repo includes a Paris OSM-grid showcase, committed benchmark baselines,
schema validation, release-bundle byte gates, and a local static viewer.

Repo: https://github.com/rsasaki0109/roadgraph_builder

## X / Bluesky

I built `roadgraph_builder`: a Python toolkit that turns GPS trajectories / OSM
ways into inspectable road graphs.

Exports nav JSON, simulation GeoJSON, and Lanelet2-style OSM. Includes routing,
turn restrictions, reachability, LiDAR/camera hooks, schemas, benchmarks, and a
Paris map preview.

https://github.com/rsasaki0109/roadgraph_builder

## LinkedIn

I have been working on `roadgraph_builder`, a graph-first road map toolkit for
Python.

The project builds road topology from GPS trajectories or OSM highway ways and
keeps the output as explicit nodes, edges, centerline polylines, and attributes.
From that single representation it can export navigation JSON, simulation
GeoJSON, and Lanelet2-style OSM.

The current version includes turn-restriction-aware routing, reachability
analysis, lane-change and slope-aware route costs, LiDAR / camera integration
hooks, JSON Schema validation, benchmark baselines, and a Paris OSM-grid map
preview.

The goal is not to pretend this is a finished survey-grade HD map generator.
The goal is to provide a transparent, testable intermediate representation for
mapping, robotics, autonomy, GIS, and simulation workflows.

Repo: https://github.com/rsasaki0109/roadgraph_builder

## Hacker News / Reddit

I built a small Python toolkit for constructing road graphs from GPS
trajectories or OSM highway ways.

The core idea is to keep the intermediate map representation explicit:
`Graph(nodes, edges)`, centerline polylines, and JSON-serializable attributes.
From that graph, the project exports:

- navigation JSON,
- simulation GeoJSON,
- Lanelet2-style OSM XML,
- manifest / provenance JSON,
- route and reachability GeoJSON overlays.

Routing supports turn restrictions, confidence filters, observed/unobserved
edge weighting, slope costs, lane-change costs, and prepared planners for
repeated shortest-path and reachability queries.

The repo also includes a Paris OSM-derived showcase, benchmark baselines,
schema validation, CI, and byte-for-byte release-bundle tests.

Repo: https://github.com/rsasaki0109/roadgraph_builder

## Three Command Demo

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/roadgraph_builder export-bundle examples/sample_trajectory.csv /tmp/rg_bundle --origin-json examples/toy_map_origin.json --lane-width-m 3.5
.venv/bin/roadgraph_builder route /tmp/rg_bundle/sim/road_graph.json n0 n1 --output /tmp/route.geojson
```

## Visuals To Attach

- Route diagnostics comparison: `docs/images/route_diagnostics_compare.png`
- README image: `docs/images/paris_grid_route.svg`
- Interactive local map: `docs/map.html`
- Architecture: `docs/ARCHITECTURE.md`
- Benchmarks: `docs/benchmarks.md`

## Caveats To Say Clearly

- This is graph-first mapping infrastructure, not a finished cm-class HD map product.
- OSM-derived assets require ODbL attribution.
- Private repository GitHub Pages may require a paid plan or public visibility.
- PyPI publishing is scaffolded but intentionally skipped unless explicitly enabled.
