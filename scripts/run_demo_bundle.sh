#!/usr/bin/env bash
# Demo: validate inputs, export-bundle (toy origin), validate outputs.
# Usage: ./scripts/run_demo_bundle.sh [output_dir]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
RB="${RB:-$ROOT/.venv/bin/roadgraph_builder}"
if [[ ! -f "$RB" ]]; then
  echo "Install the package first: python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi
OUT="${1:-/tmp/roadgraph_demo_bundle}"
"$RB" validate-detections examples/camera_detections_sample.json
"$RB" validate-turn-restrictions examples/turn_restrictions_sample.json
"$RB" export-bundle examples/sample_trajectory.csv "$OUT" \
  --origin-json examples/toy_map_origin.json \
  --lane-width-m 3.5 \
  --detections-json examples/camera_detections_sample.json \
  --turn-restrictions-json examples/turn_restrictions_sample.json \
  --dataset-name demo
"$RB" validate-sd-nav "$OUT/nav/sd_nav.json"
"$RB" validate "$OUT/sim/road_graph.json"
"$RB" validate-manifest "$OUT/manifest.json"
echo "OK: $OUT (open sim/map.geojson in QGIS or use lanelet/map.osm in JOSM)"
