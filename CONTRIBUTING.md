# Contributing to roadgraph_builder

Thanks for your interest. This repo is a personal project that accepts
external contributions; the notes below keep the signal-to-noise high so
patches can land quickly.

Before diving in, open [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) —
it has a one-page map (Mermaid diagrams + module index) that makes the
rest of the codebase readable.

## Dev setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
make test           # pytest, Python 3.10 / 3.12 validated in CI
make demo           # full pipeline smoke test (writes /tmp/roadgraph_demo_bundle)
```

Optional extra for LAZ support:

```bash
.venv/bin/pip install -e ".[laz]"       # adds laspy[lazrs]
```

## What I look for in a PR

1. **One coherent change per commit.** Feature + its tests + schema /
   CHANGELOG updates belong together; don't split into "module only",
   "tests only", "docs only" PRs.
2. **A test case.** Every new function / CLI flag / schema field either
   has a unit test under `tests/` or is exercised by the existing
   end-to-end CLI test (`tests/test_cli_end_to_end.py`). Target stays
   at "green on `make test`".
3. **Schema discipline.** If you change a JSON schema under
   `roadgraph_builder/schemas/`, update the matching
   `roadgraph_builder/validation/validate_*_document` and make sure
   `roadgraph_builder doctor` still exits 0.
4. **CHANGELOG entry.** Add a bullet under `## [Unreleased]`. Keep the
   existing categories (`Added` / `Changed` / `Fixed` / `Documentation`).
5. **No Co-Authored-By trailer, no AI-assistant markers** in commit
   messages or PR descriptions. That convention is enforced at the user
   level (`~/.claude/CLAUDE.md`) and matches the existing history.
6. **Data hygiene.** Do not commit raw external datasets (OSM GPS CSVs
   > ~100 KB, LAS point clouds, IMEIs, credentials, raw dumps).
   Derivatives (a bundled `map_*.geojson`) are fine with proper
   attribution in `docs/assets/ATTRIBUTION.md`.

## Branching / releases

- Day-to-day work lands on `main` directly. There's no PR review gate;
  keep commits focused so `git log --oneline` stays readable.
- Releases are cut by pushing a `v*` tag; that triggers
  `.github/workflows/release.yml` which builds the sample bundle and
  attaches it to a GitHub Release. The maintainer decides when to tag.
- `.github/workflows/pypi.yml` is a `workflow_dispatch` scaffold for
  PyPI publishing via Trusted Publisher. It is opt-in and requires
  a one-time PyPI-side setup; no repo secrets are used.

## Running the CLI end-to-end

```bash
# Build everything from the toy trajectory
roadgraph_builder export-bundle examples/sample_trajectory.csv /tmp/rg_bundle \
  --origin-json examples/toy_map_origin.json \
  --lane-width-m 3.5 \
  --detections-json examples/camera_detections_sample.json \
  --turn-restrictions-json examples/turn_restrictions_sample.json \
  --lidar-points examples/sample_lidar.las

# Validate every artefact
roadgraph_builder validate-manifest /tmp/rg_bundle/manifest.json
roadgraph_builder validate-sd-nav /tmp/rg_bundle/nav/sd_nav.json
roadgraph_builder validate /tmp/rg_bundle/sim/road_graph.json

# Routing demo
roadgraph_builder route /tmp/rg_bundle/sim/road_graph.json n0 n1 --output /tmp/route.geojson
```

For the Leaflet viewer:

```bash
cd docs && python3 -m http.server 8765
# then open http://127.0.0.1:8765/map.html
```

## Bug reports / questions

Open an issue on GitHub with a short repro. Including the output of
`roadgraph_builder doctor` is usually enough to get started.
