#!/usr/bin/env bash
# One-shot bundle for parameter tuning: writes OUT and prints paths + validation.
# Usage:
#   ./scripts/run_tuning_bundle.sh [OUT_DIR] [trajectory.csv] [origin.json]
# Defaults: /tmp/roadgraph_tune_bundle, examples/sample_trajectory.csv, examples/toy_map_origin.json
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
RB="${RB:-$ROOT/.venv/bin/roadgraph_builder}"
if [[ ! -f "$RB" ]]; then
  echo "Install the package first: python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

OUT="${1:-/tmp/roadgraph_tune_bundle}"
CSV="${2:-examples/sample_trajectory.csv}"
ORIGIN="${3:-examples/toy_map_origin.json}"

echo "== roadgraph_builder tuning bundle =="
echo "OUT=$OUT"
echo "CSV=$CSV"
echo "ORIGIN=$ORIGIN"
echo ""

"$RB" export-bundle "$CSV" "$OUT" \
  --origin-json "$ORIGIN" \
  --lane-width-m 3.5 \
  --dataset-name tuning

"$RB" validate-manifest "$OUT/manifest.json"
"$RB" validate-sd-nav "$OUT/nav/sd_nav.json"
"$RB" validate "$OUT/sim/road_graph.json"

echo ""
echo "OK. Open GeoJSON:"
echo "  $OUT/sim/map.geojson"
echo "Tune parameters (see docs/bundle_tuning.md), then re-run the same command."
echo "Example (noisy OSM sample):"
echo "  $0 /tmp/osm_tune examples/osm_public_trackpoints.csv examples/osm_public_trackpoints_origin.json"
