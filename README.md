# roadgraph_builder

Construct road graphs from trajectory, LiDAR, and camera data.

## Concept

- **Graph first** — The road structure is a graph (nodes/edges); centerlines and boundaries are geometric attributes attached to that structure rather than defining it alone.
- **Multi-modal** — Trajectory, LiDAR, and camera inputs are separate, swappable modules; fusion is an explicit later stage (not baked into the core graph model).
- **Toward SD/HD maps** — The JSON graph is an intermediate representation you can enrich (semantics, topology) before exporting to map formats.

## Requirements

- Python 3.10+
- `numpy`, `jsonschema` (for validating exported JSON)

## Install

From the repository root (use a virtual environment on PEP 668–managed systems):

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Public trajectory sample (OpenStreetMap)

The file `examples/osm_public_trackpoints.csv` is **real, publicly contributed GPS data** fetched from the OpenStreetMap API (`/api/0.6/trackpoints`). It is intended for tuning `build` / `visualize` on noisy trajectories.

- **License / attribution:** OpenStreetMap data is © OpenStreetMap contributors and available under the **Open Database License (ODbL)**. See [openstreetmap.org/copyright](https://www.openstreetmap.org/copyright).
- **Regenerate** (optional; requires network): from the repo root, after editing `USER_AGENT` in the script if you publish a fork:

```bash
python3 scripts/fetch_osm_trackpoints.py -o examples/osm_public_trackpoints.csv
```

Try another area if the bbox has no uploads: `--bbox min_lon,min_lat,max_lon,max_lat` (each side ≤ 0.25°).

Example (defaults are fine; **starting point for the committed OSM sample**):

```bash
roadgraph_builder build examples/osm_public_trackpoints.csv osm_graph.json \
  --max-step-m 40 --merge-endpoint-m 12 --centerline-bins 32
roadgraph_builder visualize examples/osm_public_trackpoints.csv osm_preview.svg \
  --max-step-m 40 --merge-endpoint-m 12 --centerline-bins 32
```

## Usage (CLI)

```bash
roadgraph_builder build examples/sample_trajectory.csv out.json
```

Optional tuning:

```bash
roadgraph_builder build input.csv out.json --max-step-m 25 --merge-endpoint-m 8 --centerline-bins 32
```

- `--max-step-m` — Split the time-ordered path when consecutive samples are farther apart (meters); mimics trip/gap segmentation (MVP “clustering”).
- `--merge-endpoint-m` — Snap nearby polyline endpoints into one graph node (meters).
- `--centerline-bins` — PCA bin count for smoothing each segment’s centerline.

### Visualize (SVG)

Renders raw trajectory points, edge polylines, and node IDs (no extra dependencies beyond NumPy):

```bash
roadgraph_builder visualize examples/sample_trajectory.csv preview.svg
```

### Tuning workflow (recommended)

1. Run `build` on your CSV, then `visualize` to the same base name (`.svg`).
2. **Too many short edges** — increase `--max-step-m` so small GPS jumps do not split the path.
3. **Too few edges / merged roads** — decrease `--max-step-m` to split at real gaps (parking ↔ road, ferry, etc.).
4. **Duplicate nodes at one junction** — increase `--merge-endpoint-m` so nearby endpoints snap together.
5. **Over-merged junctions** — decrease `--merge-endpoint-m`.
6. **Jagged centerline** — raise `--centerline-bins` for smoother polylines, or lower if you need fewer points.

### Validate JSON (schema)

Exports include **`schema_version`** (currently `1`) and are described by `roadgraph_builder/schemas/road_graph.schema.json` (JSON Schema Draft 2020-12).

```bash
roadgraph_builder build examples/sample_trajectory.csv out.json
roadgraph_builder validate out.json
```

### Tests

```bash
.venv/bin/pip install -e ".[dev]"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` avoids loading broken global `pytest` plugins on some systems (for example ROS) that are unrelated to this project.

### CI

GitHub Actions (`.github/workflows/ci.yml`) runs `pytest` on Python 3.10 and 3.12 for every push and pull request to `main`/`master`. Push this repository to GitHub (or fork) to run the workflow on the server.

## Package layout

Python package: `roadgraph_builder/`

| Path | Role |
| --- | --- |
| `roadgraph_builder/core/graph/` | Node, Edge, Graph models |
| `roadgraph_builder/io/trajectory/` | Trajectory CSV loader |
| `roadgraph_builder/io/lidar/` | LiDAR loader stubs (future) |
| `roadgraph_builder/io/camera/` | Camera loader stubs (future) |
| `roadgraph_builder/io/export/` | JSON exporter; Lanelet2 stub (`export_lanelet2`) |
| `roadgraph_builder/pipeline/` | `build_graph` pipeline |
| `roadgraph_builder/utils/geometry.py` | Clustering / centerline helpers |
| `roadgraph_builder/viz/` | SVG export (trajectory + graph) |
| `roadgraph_builder/semantics/` | Placeholder for lane semantics (separate from geometry) |
| `roadgraph_builder/schemas/` | JSON Schema for exported graphs |
| `roadgraph_builder/validation/` | `validate_road_graph_document()` |
| `roadgraph_builder/cli/` | CLI |

## Future extensions

- **LiDAR** — Edge-aligned boundary polylines, width hints, elevation.
- **Camera** — Per-edge semantics (signals, stop lines, signs) as attributes.
- **Semantics layer** — Dedicated module for lane type, rules, and priority (separate from raw geometry).
- **Lanelet2 export** — Serialize enriched graphs to Lanelet2/OSM-style outputs.

Codebase TODOs also mention: graph fusion across tiles/modalities, intersection topology inference, and routing graph generation.

## License

Add a license file as needed for your OSS project.
