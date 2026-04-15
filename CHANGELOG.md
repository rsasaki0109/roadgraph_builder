# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Douglas–Peucker** polyline simplification (`BuildParams.simplify_tolerance_m`, CLI `--simplify-tolerance`).
- **Node topology attributes:** `degree` and `junction_hint` (dead-end / through / multi-branch) via `annotate_node_degrees()`.
- **`Node.attributes`** on export (optional in JSON schema).

### Changed

- **`visualize` SVG** — map-inspired styling (grid, trajectory polyline, road-width stroke under centerline, scale bar, refreshed `docs/images` for README).

## [0.2.0] — 2026-04-15

### Added

- **`docs/`** static site: interactive pan/zoom viewer for graph JSON + trajectory CSV (GitHub Pages–ready).
- **`scripts/refresh_docs_assets.py`** — rebuild `docs/assets` and README preview SVGs from `examples/`.
- **README** preview images under `docs/images/` (toy + OSM samples).

### Changed

- **`visualize` SVG** — gradient background and soft glow on centerlines.

## [0.1.0] — 2026-04-15

### Added

- Graph-first JSON export (`schema_version`, nodes, edges with centerline polylines).
- CLI: `build`, `visualize` (SVG), `validate` (JSON Schema).
- Trajectory CSV loader and MVP pipeline (gap segmentation, PCA centerline, endpoint merge).
- OSM public GPS sample (`examples/osm_public_trackpoints.csv`) and fetch script.
- Tests and CI (Python 3.10 / 3.12).
- Stubs: LiDAR, camera, Lanelet2 export.

[0.2.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.2.0
[0.1.0]: https://github.com/rsasaki0109/roadgraph_builder/releases/tag/v0.1.0
