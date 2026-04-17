#!/usr/bin/env bash
# Deterministic release bundle: export-bundle on the toy sample, validate every
# artifact, and pack as dist/roadgraph_sample_bundle.tar.gz (+ sha256).
# Usage: bash scripts/build_release_bundle.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RB="${RB:-$ROOT/.venv/bin/roadgraph_builder}"
if [[ ! -x "$RB" ]]; then
  if command -v roadgraph_builder >/dev/null 2>&1; then
    RB="$(command -v roadgraph_builder)"
  else
    echo "Install the package first: python3 -m venv .venv && .venv/bin/pip install -e \".[dev]\"" >&2
    exit 1
  fi
fi

DIST="$ROOT/dist"
OUT="$DIST/roadgraph_sample_bundle"
TAR="$DIST/roadgraph_sample_bundle.tar.gz"
SHA="$DIST/roadgraph_sample_bundle.sha256"

rm -rf "$OUT" "$TAR" "$SHA"
mkdir -p "$DIST"

echo "== roadgraph_builder release bundle =="
echo "OUT=$OUT"

"$RB" validate-detections examples/camera_detections_sample.json
"$RB" validate-turn-restrictions examples/turn_restrictions_sample.json

"$RB" export-bundle examples/sample_trajectory.csv "$OUT" \
  --origin-json examples/toy_map_origin.json \
  --lane-width-m 3.5 \
  --detections-json examples/camera_detections_sample.json \
  --turn-restrictions-json examples/turn_restrictions_sample.json \
  --lidar-points examples/sample_lidar.las \
  --fuse-max-dist-m 5.0 \
  --fuse-bins 16 \
  --dataset-name roadgraph_sample_bundle

"$RB" validate-manifest "$OUT/manifest.json"
"$RB" validate-sd-nav "$OUT/nav/sd_nav.json"
"$RB" validate "$OUT/sim/road_graph.json"

# Pack deterministically: sort entries, drop atime/mtime jitter.
# Use the fixed bundle name so the archive top-level directory matches.
tar \
  --sort=name \
  --owner=0 --group=0 --numeric-owner \
  --mtime='UTC 1970-01-01' \
  -C "$DIST" \
  -czf "$TAR" \
  roadgraph_sample_bundle

( cd "$DIST" && sha256sum "$(basename "$TAR")" > "$(basename "$SHA")" )

echo "OK: $TAR"
echo "    $SHA"
