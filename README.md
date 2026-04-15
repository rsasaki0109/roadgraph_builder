# roadgraph_builder

**Construct road graphs from trajectory, LiDAR, and camera data** (MVP: **trajectory CSV only**).

This project builds a **graph-first** intermediate representation: **nodes** (junctions/endpoints) and **edges** (lane/road segments) with **centerline polylines** and optional **attributes**. Output is **JSON** (`schema_version`) with optional **SVG** previews and an **interactive viewer** on **GitHub Pages** (`docs/`).

### GitHub “About” text (copy-paste)

Use the short description and topics listed in [`.github/ABOUT.md`](.github/ABOUT.md), or run `gh repo edit` (see below).

### Features

| Area | What works today |
| --- | --- |
| **Input** | Trajectory CSV (`timestamp`, `x`, `y`) |
| **Pipeline** | Gap-based segmentation → PCA centerline → endpoint merge → graph |
| **Output** | JSON graph + `visualize` SVG + schema validation |
| **Demo** | [Diagram viewer](https://rsasaki0109.github.io/roadgraph_builder/) · **[Map (OSM tiles)](https://rsasaki0109.github.io/roadgraph_builder/map.html)** (enable Pages on `/docs`), static previews in [docs/images](docs/images/) |
| **Samples** | [Toy CSV](examples/sample_trajectory.csv), [OSM GPS](examples/osm_public_trackpoints.csv) (ODbL) |
| **Next** | LiDAR / camera / Lanelet2 **stubs** for modular extension |

### Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/roadgraph_builder build examples/sample_trajectory.csv out.json
.venv/bin/roadgraph_builder validate out.json
```

### Links

| Resource | URL |
| --- | --- |
| **Live viewer** (after Pages) | `https://rsasaki0109.github.io/roadgraph_builder/` |
| **Changelog** | [CHANGELOG.md](CHANGELOG.md) |
| **PyPI** | Not published by default; see [PyPI (optional)](#pypi-optional) |

### Forks: URLs and OSM User-Agent

- **`scripts/refresh_docs_assets.py`** — set `ROADGRAPH_REPO_URL` and `ROADGRAPH_PAGES_URL` before running to rewrite `docs/assets/site.json` (footer links in the viewer).
- **`scripts/fetch_osm_trackpoints.py`** — set `ROADGRAPH_USER_AGENT` or pass `--user-agent` (OpenStreetMap [policy](https://operations.osmfoundation.org/policies/api/)).

## Concept

- **Graph first** — The road structure is a graph (nodes/edges); centerlines and boundaries are geometric attributes attached to that structure rather than defining it alone.
- **Multi-modal** — Trajectory, LiDAR, and camera inputs are separate, swappable modules; fusion is an explicit later stage (not baked into the core graph model).
- **Toward SD/HD maps** — The JSON graph is an intermediate representation you can enrich (semantics, topology) before exporting to map formats.

### SD map vs HD map (and this repo)

| | **SD map** (navigation / fleet) | **HD map** (AD / ADAS) |
| --- | --- | --- |
| **Typical use** | Routing, ETA, coarse “which roads connect” | Lane keeping, planning in lane coordinates, rules & obstacles |
| **Geometry** | Often **meter–tens of m** is acceptable for links | Often **lane boundaries**, **cm-class** accuracy in many specs |
| **Common inputs** | GNSS traces, road-network DBs, crowd probes | LiDAR, cameras, RTK/IMU, surveys, HD anchors |
| **This project today** | **Good fit as a seed:** graph + centerlines + topology attributes (`degree`, `junction_hint`), plus GeoJSON on OSM tiles for sanity checks | **Not HD-complete:** lane **boundaries** are not produced yet; LiDAR/camera are **stubs**; Lanelet2 / full semantics are **future** work |

**日本語で一言:** **SD** に向けた「道路のつながり＋中心線」の**中間表現**には使える。**HD** に必要な**レーン境界・高精度・規則**は、別データ（LiDAR 等）とセマンティクス層を足してから、という前提。

### What you get (and what you do not)

- **You get** a **road graph** (nodes and edges) with **centerline polylines** in the **same units as your CSV** (often meters after projection). That is **intermediate data** for fusion, mapping tools, or simulation—not a finished HD product by itself.
- **Do not expect** satellite-style photo maps, automatic alignment to aerial imagery, or perfect lane shapes without **tuning** (`max-step-m`, `merge-endpoint-m`, bin count, and data quality). GPS noise and dropouts directly affect the result.
- **`visualize` SVG** is a **diagram** (road-shaped centerlines, trajectory, nodes)—**not** aerial imagery or a finished “map product” yet. We are iterating on readability until it feels closer to a usable map view.

### Preview (images)

These are **static exports** from `roadgraph_builder visualize` (regenerate with `scripts/refresh_docs_assets.py`). They use a **map-inspired** style (grid, pseudo road width, scale bar) while staying honest about the data: **geometry comes from your CSV**, not from a satellite basemap.

**Toy trajectory** (small synthetic path):

![Toy trajectory sample](docs/images/sample_trajectory.svg)

**OSM public GPS** (real noisy samples; parameters tuned for the bundled CSV):

![OSM public GPS sample](docs/images/osm_public.svg)

> **まだ「地図」では？** — 衛星写真や地図タイルのような“地図”ではありませんが、**道路構造を読むための図**としてはここまで寄せています。これからも見た目とアルゴリズムを詰めていきます。

### Interactive viewer (GitHub Pages)

The **`docs/`** folder is a small static site.

1. In the GitHub repo: **Settings → Pages → Build and deployment → Source**: **Deploy from a branch**, branch **`main`**, folder **`/docs`**, Save.
2. After a minute, open:
   - **`https://<user>.github.io/roadgraph_builder/`** — diagram viewer (SVG-style pan/zoom)
   - **`https://<user>.github.io/roadgraph_builder/map.html`** — **real basemap** (OpenStreetMap raster tiles + GeoJSON overlay: trajectory, centerlines, nodes)

Local preview (no GitHub required):

```bash
cd docs && python3 -m http.server 8765
# http://127.0.0.1:8765/          — diagram viewer
# http://127.0.0.1:8765/map.html  — OSM map + GeoJSON
```

Regenerate bundled JSON/CSV/SVG for `docs/` after changing examples or pipeline logic:

```bash
python3 scripts/refresh_docs_assets.py
```

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
- **Regenerate** (optional; requires network): set a fork-specific agent if needed, then run:

```bash
export ROADGRAPH_USER_AGENT='myfork/1.0 (+https://github.com/you/roadgraph_builder)'
python3 scripts/fetch_osm_trackpoints.py -o examples/osm_public_trackpoints.csv
```

Also writes **`examples/osm_public_trackpoints_origin.json`** (WGS84 origin for the meters CSV) and **`examples/osm_public_trackpoints_wgs84.csv`** (`timestamp,lon,lat`) for map tooling.

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
- `--simplify-tolerance` — Douglas–Peucker tolerance (meters) to thin edge polylines after centerline fit; omit to keep all centerline points.

**Node metadata (topology):** each exported node may include `attributes.degree` (undirected edge count) and `attributes.junction_hint` (`dead_end`, `through_or_corner`, `multi_branch`).

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
| `docs/` | GitHub Pages viewer + bundled sample assets |
| `scripts/refresh_docs_assets.py` | Regenerate `docs/assets` and `docs/images` |
| `roadgraph_builder/io/export/geojson.py` | `export_map_geojson()` for Leaflet / OSM |
| `roadgraph_builder/utils/geo.py` | meters ↔ WGS84 (local tangent plane) |
| `.github/ABOUT.md` | Short text + topics for GitHub **About** |

## Future extensions

- **LiDAR** — Edge-aligned boundary polylines, width hints, elevation.
- **Camera** — Per-edge semantics (signals, stop lines, signs) as attributes.
- **Semantics layer** — Dedicated module for lane type, rules, and priority (separate from raw geometry).
- **Lanelet2 export** — Serialize enriched graphs to Lanelet2/OSM-style outputs.

Codebase TODOs also mention: graph fusion across tiles/modalities, intersection topology inference, and routing graph generation.

## Releases

Changes are listed in [CHANGELOG.md](CHANGELOG.md).

Tag and push a version (example `v0.1.0`):

```bash
git tag -a v0.1.0 -m "Release 0.1.0"
git push origin main
git push origin v0.1.0
```

On GitHub, open **Releases → Create a new release**, select that tag, and paste the notes from `CHANGELOG.md`.

## PyPI (optional)

The distribution name in `pyproject.toml` is `roadgraph-builder`. Publishing is manual unless you add your own automation:

1. Create a [PyPI](https://pypi.org/) account and an **API token** with upload permission for this project.
2. Install build tools: `python -m pip install build twine`.
3. From a clean checkout: `python -m build` then `twine upload dist/*` (use API token when prompted).

For hands-off uploads from GitHub, configure [Trusted Publishers](https://docs.pypi.org/trusted-publishers/) or a `PYPI_API_TOKEN` secret and a workflow in your fork—this repository does not ship token-based publish secrets.

## License

Add a license file as needed for your OSS project.
