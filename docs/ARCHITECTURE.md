# roadgraph_builder — Architecture

A single-page map of how the pieces fit together. Skim the diagrams first,
then drop into the module index at the bottom. The intent is to give a new
contributor (or a future Codex session) enough context to know *where* to
change things.

## High-level data flow

Inputs enter from the left; the three export targets and the interactive
viewer live on the right. Optional stages are dashed.

```mermaid
flowchart LR
    subgraph Inputs
        T[Trajectory CSV<br/>timestamp,x,y]
        O[Origin JSON<br/>lat0,lon0]
        D[Camera detections JSON<br/>observations: edge_id, kind, ...]
        L[LiDAR points<br/>CSV or LAS/LAZ]
        R[Turn restrictions JSON<br/>manual or sd_nav shape]
        HW[OSM highway ways<br/>Overpass JSON]
        OSMR[OSM type=restriction<br/>Overpass JSON]
        IMG[Image-space detections<br/>+ camera calibration]
    end

    T --> B[build<br/>pipeline.build_graph]
    HW --> BOG[build-osm-graph<br/>io.osm.graph_builder]
    B --> G((Graph<br/>nodes, edges<br/>metadata.map_origin))
    BOG --> G

    G -->|lane_width_m > 0| E[enrich<br/>hd.pipeline]
    E --> G

    L -. optional .-> F[fuse-lidar<br/>hd.lidar_fusion]
    F -. attributes.hd.lane_boundaries .-> G

    D -. optional .-> C[apply-camera<br/>io.camera.detections]
    C -. attributes.hd.semantic_rules .-> G

    IMG -. optional .-> PC[project-camera<br/>io.camera.pipeline]
    PC -. edge-keyed camera_detections.json .-> D

    OSMR -. optional .-> COR[convert-osm-restrictions<br/>io.osm.turn_restrictions]
    COR -. turn_restrictions.json .-> R

    R -. optional .-> TR[turn_restrictions<br/>navigation.turn_restrictions]
    TR -. merged list .-> NAV

    G --> NAV[nav/sd_nav.json<br/>topology + lengths<br/>allowed_maneuvers<br/>turn_restrictions]
    G --> SIM[sim/road_graph.json<br/>sim/map.geojson<br/>sim/trajectory.csv]
    G --> LL[lanelet/map.osm<br/>OSM XML 0.6]
    G --> MAN[manifest.json<br/>graph_stats, junctions,<br/>lidar_points, turn_restrictions_*]

    O --> B
    O --> NAV
    O --> SIM
    O --> LL

    SIM --> V[docs/map.html<br/>Leaflet viewer<br/>TR-aware JS Dijkstra]
```

## Packages

```mermaid
flowchart TD
    subgraph core.graph
        Graph
        Node
        Edge
        stats.graph_stats
        stats.junction_stats
    end

    subgraph pipeline
        build_graph
        junction_topology
    end

    subgraph hd
        pipeline_hd[hd.pipeline]
        boundaries
        lidar_fusion
        refinement
    end

    subgraph io
        trajectory.loader
        camera.detections
        camera.calibration
        camera.projection
        camera.pipeline
        lidar.points
        lidar.las
        lidar.fusion
        lidar.lane_marking
        osm.graph_builder
        osm.turn_restrictions
        export.geojson
        export.json_exporter
        export.json_loader
        export.lanelet2
        export.bundle
    end

    subgraph semantics
        trace_fusion
        trip_reconstruction
        road_class
        signalized
    end

    subgraph navigation
        sd_maneuvers
        turn_restrictions
        guidance
    end

    subgraph routing
        shortest_path
        nearest
        geojson_export
    end

    subgraph schemas_validation[schemas + validation]
        road_graph.schema
        sd_nav.schema
        manifest.schema
        camera_detections.schema
        turn_restrictions.schema
        lane_markings.schema
        guidance.schema
    end

    subgraph cli
        main
        doctor
    end

    pipeline --> core.graph
    hd --> core.graph
    io --> core.graph
    navigation --> core.graph
    routing --> core.graph
    semantics --> core.graph
    semantics --> routing

    export.bundle --> pipeline
    export.bundle --> hd
    export.bundle --> navigation
    export.bundle --> io
    export.bundle --> core.graph

    cli --> pipeline
    cli --> hd
    cli --> io
    cli --> navigation
    cli --> routing
    cli --> schemas_validation
```

## CLI surface

Every subcommand maps to a tight slice of the library. The CLI itself is a
thin argparse dispatcher in `roadgraph_builder/cli/main.py`.

| Command | Reads | Writes / emits | Library entry point |
| --- | --- | --- | --- |
| `doctor` | repo cwd, package resources | stdout summary; exit 1 on schema/LAS failure | `cli.doctor.run_doctor` |
| `build` | trajectory CSV | road_graph JSON | `pipeline.build_graph.build_graph_from_csv` |
| `visualize` | trajectory CSV | SVG | `viz.svg_export.write_trajectory_graph_svg` |
| `validate` / `validate-detections` / `validate-sd-nav` / `validate-manifest` / `validate-turn-restrictions` | a JSON doc | — (exit 0 / 1) | `validation.*_document` |
| `enrich` | road_graph JSON | road_graph JSON with `metadata.sd_to_hd` / `attributes.hd` | `hd.pipeline.enrich_sd_to_hd` |
| `fuse-lidar` | road_graph + CSV/LAS/LAZ points | road_graph JSON with per-edge boundaries | `hd.lidar_fusion.fuse_lane_boundaries_from_points` |
| `apply-camera` | road_graph + detections JSON | road_graph JSON with `attributes.hd.semantic_rules` | `io.camera.detections.apply_camera_detections_to_graph` |
| `export-lanelet2` | road_graph + origin | OSM XML 0.6 | `io.export.lanelet2.export_lanelet2` |
| `export-bundle` | trajectory + origin (+ optional detections / LAS / turn_restrictions) | `nav/`, `sim/`, `lanelet/`, `manifest.json` | `io.export.bundle.export_map_bundle` |
| `inspect-lidar` | `.las` | LAS header JSON | `io.lidar.las.read_las_header` |
| `stats` | road_graph | `{graph_stats, junctions}` JSON | `core.graph.stats.graph_stats` / `junction_stats` |
| `nearest-node` | road_graph + query point | `{node_id, distance_m, query_xy_m}` JSON | `routing.nearest.nearest_node` |
| `route` | road_graph + (node ids or lat/lon) + optional restrictions | route JSON (+ optional GeoJSON via `--output`) | `routing.shortest_path` / `routing.geojson_export.write_route_geojson` |
| `match-trajectory` | road_graph + trajectory CSV | per-sample snap JSON + coverage summary | `routing.map_match.snap_trajectory_to_graph` / `routing.hmm_match.hmm_match_trajectory` |
| `fuse-traces` | road_graph + list of trajectories | road_graph JSON with `attributes.trace_stats` | `semantics.trace_fusion.fuse_traces_into_graph` |
| `reconstruct-trips` | road_graph + long trajectory | trip list JSON | `semantics.trip_reconstruction.reconstruct_trips` |
| `infer-road-class` | road_graph + trajectory | road_graph JSON with per-edge speed / class | `semantics.road_class.infer_road_class` |
| `infer-signalized-junctions` | road_graph + trajectory | road_graph JSON with `signalized_candidate` node tags | `semantics.signalized.infer_signalized_junctions` |
| `build-osm-graph` | raw Overpass JSON (highway ways) + origin | road_graph JSON | `io.osm.graph_builder.build_graph_from_overpass_highways` |
| `convert-osm-restrictions` | road_graph + Overpass JSON (restriction relations) | `turn_restrictions.json` (schema-valid) | `io.osm.turn_restrictions.convert_osm_restrictions_to_graph` |
| `project-camera` | camera calibration + image detections + road_graph | `camera_detections.json` (edge-keyed) | `io.camera.pipeline.project_image_detections_to_graph_edges` |
| `detect-lane-markings` | road_graph + LAS/LAZ points (with intensity) | `lane_markings.json` (per-edge left/right/center candidates) | `io.lidar.lane_marking.detect_lane_markings` |
| `detect-lane-markings-camera` (0.7) | camera calibration + image RGB + road_graph + vehicle pose | lane-candidate JSON (image-space → world → nearest edge) | `io.camera.lane_detection.detect_lanes_from_image_rgb` + `project_camera_lanes_to_graph_edges` |
| `validate-lane-markings` | a `lane_markings.json` | — (exit 0 / 1) | `validation.validate_lane_markings_document` |
| `guidance` | route GeoJSON + sd_nav JSON | `guidance.json` (turn-by-turn step list) | `navigation.guidance.build_guidance` |
| `validate-guidance` | a `guidance.json` | — (exit 0 / 1) | `validation.validate_guidance_document` |
| `infer-lane-count` (0.6) | road_graph (+ optional `lane_markings.json`) | road_graph JSON with `attributes.hd.lane_count` + `hd.lanes[]` | `hd.lane_inference.infer_lane_count` |
| `validate-lanelet2-tags` (0.6) | OSM XML (from `export-lanelet2`) | — (exit 1 on missing required tags; warnings for missing speed_limit) | `io.export.lanelet2_tags_validator` |
| `validate-lanelet2` (0.7) | OSM XML + `lanelet2_validation` on PATH | structured JSON `{status, errors, warnings, ...}` | `io.export.lanelet2_validator_bridge` |
| `update-graph` (0.7) | existing road_graph + new trajectory CSV | merged road_graph JSON (absorb or append) | `pipeline.incremental.update_graph_from_trajectory` |
| `process-dataset` (0.7) | input dir of CSVs + origin | `dataset_manifest.json` + per-file export bundles | `cli.dataset.process_dataset` |

## `export-bundle` internals

```mermaid
sequenceDiagram
    participant U as User
    participant CLI as roadgraph_builder CLI
    participant BG as pipeline.build_graph
    participant HD as hd.pipeline + lidar_fusion
    participant CAM as io.camera.detections
    participant TR as navigation.turn_restrictions
    participant EX as io.export.*
    participant OUT as out_dir/

    U->>CLI: export-bundle CSV OUT --origin-json ...
    CLI->>BG: build_graph_from_csv(CSV)
    BG-->>CLI: Graph
    opt --lane-width-m > 0
        CLI->>HD: enrich_sd_to_hd(graph, lane_width_m)
    end
    opt --lidar-points
        CLI->>HD: fuse_lane_boundaries_from_points(graph, pts)
    end
    opt --detections-json
        CLI->>CAM: apply_camera_detections_to_graph(graph, obs)
    end
    opt --turn-restrictions-json or camera kind=turn_restriction
        CLI->>TR: load_turn_restrictions_json / turn_restrictions_from_camera_detections
        TR-->>CLI: merged list
    end
    CLI->>EX: build_sd_nav_document(graph, turn_restrictions=...)
    EX->>OUT: nav/sd_nav.json
    CLI->>EX: export_graph_json, export_map_geojson, copy trajectory.csv
    EX->>OUT: sim/road_graph.json, sim/map.geojson, sim/trajectory.csv
    CLI->>EX: export_lanelet2
    EX->>OUT: lanelet/map.osm
    CLI->>OUT: manifest.json (graph_stats, junctions, lidar_points, turn_restrictions_*)
```

## Bundle directory

```text
<out_dir>/
├── README.txt
├── manifest.json            # provenance + graph_stats + junctions + turn_restrictions_*
├── nav/
│   └── sd_nav.json          # topology + allowed_maneuvers(_reverse) + turn_restrictions
├── sim/
│   ├── README.txt
│   ├── road_graph.json      # full graph (nodes, edges with hd + attributes)
│   ├── map.geojson          # WGS84 FeatureCollection (trajectory, centerlines, boundaries, nodes)
│   └── trajectory.csv       # verbatim copy of the input
└── lanelet/
    └── map.osm              # OSM XML 0.6 with roadgraph:* tags + optional lanelet relations
```

## Schema graph

Every written artefact has a JSON Schema under `roadgraph_builder/schemas/`
and a validator in `roadgraph_builder/validation/`.

```mermaid
flowchart LR
    RG[road_graph.schema.json] -.validated by.-> vRG[validate_road_graph_document]
    SDN[sd_nav.schema.json] -.validated by.-> vSDN[validate_sd_nav_document]
    MF[manifest.schema.json] -.validated by.-> vMF[validate_manifest_document]
    CD[camera_detections.schema.json] -.validated by.-> vCD[validate_camera_detections_document]
    TR[turn_restrictions.schema.json] -.validated by.-> vTR[validate_turn_restrictions_document]
    LM[lane_markings.schema.json] -.validated by.-> vLM[validate_lane_markings_document]
    GD[guidance.schema.json] -.validated by.-> vGD[validate_guidance_document]

    SDN -.embeds.-> TR
    MF -.references.-> RG
    MF -.references.-> SDN
```

`sd_nav.schema.json` inlines the same per-item shape that
`turn_restrictions.schema.json` wraps, so a manual
`{turn_restrictions: [...]}` file validates with either validator.

## Routing subsystem

```mermaid
flowchart LR
    subgraph routing
        SP[shortest_path<br/>Dijkstra over<br/>node, incoming_edge, direction]
        NN[nearest_node]
        RGJ[build_route_geojson<br/>write_route_geojson]
    end

    N[node id] --> SP
    LL[lat, lon + origin] --> NN --> SP
    TR[turn_restrictions<br/>no_* / only_*] -.optional.-> SP
    SP --> Route((Route dataclass<br/>node_sequence<br/>edge_sequence<br/>edge_directions<br/>total_length_m))
    Route --> RGJ --> GJ[route.geojson<br/>route LineString +<br/>route_edge +<br/>route_start / route_end]
```

The Leaflet viewer (`docs/map.html`) ships a second, smaller Dijkstra in
JavaScript that reads the `start_node_id` / `end_node_id` / `length_m`
properties now emitted on every centerline feature, so click-to-route
works entirely client-side.

## Distribution & CI

```mermaid
flowchart TD
    subgraph repo[GitHub repo]
        M[main branch]
        T[(v* tag)]
    end

    M -- push --> CI[.github/workflows/ci.yml<br/>pytest + validate*<br/>+ export-bundle + doctor]
    T -- push --> REL[.github/workflows/release.yml<br/>build_release_bundle.sh<br/>tar.gz + sha256]
    M -- workflow_dispatch --> PYPI[.github/workflows/pypi.yml<br/>python -m build →<br/>pypa/gh-action-pypi-publish<br/>Trusted Publisher, no secrets]

    REL --> R[GitHub Release<br/>+ roadgraph_sample_bundle.tar.gz<br/>+ sha256]
```

## Module index

| Path | Purpose |
| --- | --- |
| `roadgraph_builder/core/graph/{graph,node,edge,stats}.py` | In-memory Graph / Node / Edge + stat helpers |
| `roadgraph_builder/pipeline/build_graph.py` | Trajectory → polylines → merged-endpoint graph (drops degenerate self-loops) |
| `roadgraph_builder/pipeline/junction_topology.py` | Classifies multi_branch nodes into `t_junction` / `y_junction` / `crossroads` / `x_junction` / `complex_junction` |
| `roadgraph_builder/hd/pipeline.py`, `boundaries.py` | SD→HD envelope, centerline-offset lane boundaries; accepts optional `refinements=` list |
| `roadgraph_builder/hd/lidar_fusion.py` | Per-edge proximity + binned median boundaries from XY point sets |
| `roadgraph_builder/hd/refinement.py` | `refine_hd_edges` — multi-source per-edge half-width + confidence from lane_markings / trace_stats / camera observations |
| `roadgraph_builder/hd/lane_inference.py` (0.6) | `infer_lane_count` — paint-marker 1-D agglomerative clustering (fallback to `trace_stats.perpendicular_offsets`) → `attributes.hd.lane_count` + `hd.lanes[]` |
| `roadgraph_builder/pipeline/incremental.py` (0.7) | `update_graph_from_trajectory` — merges a new trajectory into an existing graph; absorbs polylines within `absorb_tolerance_m` of an existing edge, else runs a restricted X/T split + endpoint union-find |
| `roadgraph_builder/cli/dataset.py` (0.7) | `process_dataset` — batch `export_map_bundle` over a directory of CSVs; `--parallel N` via `ProcessPoolExecutor`; `dataset_manifest.json` aggregates per-file status |
| `roadgraph_builder/io/trajectory/loader.py` | Trajectory CSV reader (`timestamp,x,y`) |
| `roadgraph_builder/io/camera/detections.py` | Load + apply precomputed edge-keyed camera detections (`semantic_rules` on edges) |
| `roadgraph_builder/io/camera/calibration.py` | `CameraIntrinsic` (+ optional Brown-Conrady distortion, `undistort_pixel_to_normalized`), `RigidTransform`, `CameraCalibration` (+ JSON loader) |
| `roadgraph_builder/io/camera/projection.py` | `pixel_to_ground` (pinhole ray → world ground plane), `project_image_detections` (apply to an image_detections document) |
| `roadgraph_builder/io/camera/pipeline.py` | `project_image_detections_to_graph_edges` — image-space pixels → world XY → nearest graph edge → edge-keyed observations |
| `roadgraph_builder/io/camera/lane_detection.py` (0.7) | Pure-NumPy HSV + 4-connected component labeling for white/yellow lane markings from RGB images; `project_camera_lanes_to_graph_edges` back-projects pixel centroids through `pixel_to_ground` and snaps to graph edges |
| `roadgraph_builder/io/osm/graph_builder.py` | `build_graph_from_overpass_highways` — OSM highway ways → polylines → graph (every OSM junction becomes a graph node) |
| `roadgraph_builder/io/osm/turn_restrictions.py` | `convert_osm_restrictions_to_graph` — OSM `type=restriction` relations snapped onto graph edges by via-node + tangent alignment |
| `roadgraph_builder/io/lidar/points.py` | XY CSV loader |
| `roadgraph_builder/io/lidar/las.py` | LAS 1.0–1.4 public-header reader + X/Y numpy loader; LAZ dispatch via `laspy` when the `[laz]` extra is installed |
| `roadgraph_builder/io/lidar/lane_marking.py` | `detect_lane_markings` — per-edge intensity-peak extraction that recovers left/right/center lane marking polylines from LAS/LAZ point clouds |
| `roadgraph_builder/hd/lidar_fusion.py` (0.7 update) | `fit_ground_plane_ransac` — RANSAC dominant plane from (N,3) points; `fuse_lane_boundaries_3d` filters by `height_band_m` above the ground plane before the 2D binned-median fuse |
| `roadgraph_builder/io/export/geojson.py` | WGS84 `FeatureCollection` writer (trajectory, centerlines with `start_node_id`/`end_node_id`/`length_m`, HD boundaries, nodes); optional `attribution` / `license` / `license_url` fields for derivative datasets |
| `roadgraph_builder/io/export/json_exporter.py`, `json_loader.py` | Round-trip road graph JSON |
| `roadgraph_builder/io/export/lanelet2.py` | OSM XML 0.6 exporter with `roadgraph:*` tags and optional lanelet relations; 0.6 adds `--speed-limit-tagging regulatory-element` + `--lane-markings-json` paint-based boundary `subtype`; 0.7 adds `export_lanelet2_per_lane` (1 lanelet per lane with `lane_change` relations) and `--camera-detections-json` for `traffic_light` / `stop_line` regulatory_elements. v0.7 V3 replaced the `minidom → toprettyxml` DOM round-trip with a direct `_et_to_pretty_bytes` writer (−10% peak RSS, byte-identical output) |
| `roadgraph_builder/io/export/lanelet2_tags_validator.py` (0.6) | Parses an OSM file and flags missing required `subtype` / `location` tags on lanelets (error) and missing `speed_limit` (warning) |
| `roadgraph_builder/io/export/lanelet2_validator_bridge.py` (0.7) | Wraps Autoware's `lanelet2_validation` CLI via subprocess; exit 0 on tool-absent (emits `{"status":"skipped"}`) |
| `roadgraph_builder/io/export/bundle.py` | `export_map_bundle` — the three-way export + manifest |
| `roadgraph_builder/navigation/sd_maneuvers.py` | Geometry-only `allowed_maneuvers(_reverse)` at each digitized end node |
| `roadgraph_builder/navigation/turn_restrictions.py` | Loader + camera extraction + merge for `sd_nav.turn_restrictions` |
| `roadgraph_builder/navigation/guidance.py` | `build_guidance` — turn-by-turn GuidanceStep list from route GeoJSON + sd_nav (depart / arrive / slight / left / right / sharp / u_turn / continue categories) |
| `roadgraph_builder/routing/shortest_path.py` | Directed-state Dijkstra that honours `no_*` / `only_*` restrictions; 0.6 adds `prefer_observed` / `min_confidence` cost hooks; 0.7 extends the state to `(node, incoming_edge, direction, lane_index)` for `allow_lane_change=True` with `lane_change_cost_m` swap penalty |
| `roadgraph_builder/routing/nearest.py` | `nearest_node` (xy or lat/lon) |
| `roadgraph_builder/routing/geojson_export.py` | Route → GeoJSON FeatureCollection |
| `roadgraph_builder/schemas/*.schema.json` | JSON Schemas shipped as package resources |
| `roadgraph_builder/validation/*.py` | One `validate_*_document` per schema (Draft 2020-12) |
| `roadgraph_builder/viz/svg_export.py` | Map-like SVG for the `visualize` command |
| `roadgraph_builder/cli/main.py` | argparse dispatcher for every subcommand |
| `roadgraph_builder/cli/doctor.py` | Install / asset self-check |
| `docs/map.html` | Leaflet viewer with dataset dropdown + click-to-route |
| `scripts/` | Fetch, refresh, build, demo, tune shell helpers (incl. `run_benchmarks.py` for `make bench` and `make_sample_lane_las.py` for the LiDAR lane-marking test fixtures) |
| `.github/workflows/` | CI, release-on-tag, PyPI workflow_dispatch |

## Further reading

- [`docs/PLAN.md`](PLAN.md) — roadmap, facts vs. intent, handoff pointers.
- [`docs/bundle_tuning.md`](bundle_tuning.md) — parameter sweep recipe (includes Paris / Tokyo / Berlin OSM observations).
- [`docs/navigation_turn_restrictions.md`](navigation_turn_restrictions.md) — regulation-vs-geometry design + how to provide turn restrictions.
- [`docs/handoff/turn_restrictions.md`](handoff/turn_restrictions.md), [`docs/handoff/release_distribution.md`](handoff/release_distribution.md) — Codex hand-off prompts, both marked DONE.
- [`CHANGELOG.md`](../CHANGELOG.md) — dated feature log.
