#!/usr/bin/env python3
"""Performance benchmarks for roadgraph_builder.

Measures wall-clock time for four scenarios:
  polylines_to_graph_paris       — build from OSM public trackpoints CSV
  polylines_to_graph_10k_synth   — build from 10 000-point synthetic grid
  shortest_path_paris            — 100 Dijkstra queries on the Paris graph
  export_bundle_end_to_end       — full export-bundle pipeline (sample CSV)

Usage:
    python scripts/run_benchmarks.py [--baseline baseline.json]

With --baseline, compares against a saved baseline JSON and exits 1 if any
benchmark regresses by more than 200 % (3x slower).

Output is JSON printed to stdout; stderr gets human-readable progress.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _find_paris_csv() -> Path | None:
    candidates = [
        ROOT / "examples" / "osm_public_trackpoints.csv",
        ROOT / "docs" / "assets" / "osm_trajectory.csv",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _find_sample_csv() -> Path | None:
    candidates = [
        ROOT / "examples" / "sample_trajectory.csv",
        ROOT / "docs" / "assets" / "sample_trajectory.csv",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def build_paris_graph() -> object:
    """Build graph from the OSM public-trackpoints CSV."""
    csv_path = _find_paris_csv()
    if csv_path is None:
        csv_path = _find_sample_csv()
    if csv_path is None:
        raise FileNotFoundError("No input CSV found for paris benchmark")
    from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_csv
    params = BuildParams(max_step_m=40.0, merge_endpoint_m=8.0)
    return build_graph_from_csv(str(csv_path), params)


def build_10k_synth() -> object:
    """Build graph from a synthetic trajectory with ~25 000 points.

    Generates a grid of 50 horizontal + 50 vertical lines at 10 m spacing,
    each sampled every 5 m over 500 m.  Total ~25 100 points.
    The O(N log N) fast crossing splitters (P1) make this feasible within the
    60 s budget; the old O(N²) version took ~314 s on this size.

    Grid: 50×50 = 2500 real junctions, exercising both the X-junction and
    T-junction detection paths thoroughly.
    """
    import numpy as np
    from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
    from roadgraph_builder.io.trajectory.loader import Trajectory

    # 50 horizontal + 50 vertical lines at 10 m spacing, each 500 m long.
    rows: list[tuple[float, float, float]] = []
    t = 0.0
    for row in range(50):
        y = row * 10.0
        for x in np.arange(0, 501, 5, dtype=float):
            rows.append((t, float(x), float(y)))
            t += 1.0
        t += 100.0  # gap
    for col in range(50):
        x = col * 10.0
        for y in np.arange(0, 501, 5, dtype=float):
            rows.append((t, float(x), float(y)))
            t += 1.0
        t += 100.0

    xy = np.array([[r[1], r[2]] for r in rows], dtype=np.float64)
    timestamps = np.array([r[0] for r in rows], dtype=np.float64)
    traj = Trajectory(xy=xy, timestamps=timestamps)
    params = BuildParams(max_step_m=200.0, merge_endpoint_m=8.0, centerline_bins=8)
    return build_graph_from_trajectory(traj, params)


def run_paris_routes_100() -> int:
    """Run 100 shortest-path queries on the Paris graph."""
    graph = build_paris_graph()
    nodes = graph.nodes
    if len(nodes) < 2:
        return 0
    from roadgraph_builder.routing.shortest_path import shortest_path
    n = len(nodes)
    count = 0
    for i in range(min(100, n * (n - 1))):
        src = nodes[i % n].id
        dst = nodes[(i + n // 2) % n].id
        if src == dst:
            continue
        try:
            shortest_path(graph, src, dst)
            count += 1
        except (ValueError, KeyError):
            pass
    return count


def export_bundle_paris() -> None:
    """Run the full export-bundle pipeline on the sample trajectory."""
    import tempfile
    csv_path = _find_sample_csv()
    if csv_path is None:
        return
    origin_json = ROOT / "examples" / "toy_map_origin.json"
    if not origin_json.is_file():
        return
    from roadgraph_builder.utils.geo import load_wgs84_origin_json
    lat0, lon0 = load_wgs84_origin_json(origin_json)
    from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_csv
    from roadgraph_builder.io.export.bundle import export_map_bundle
    from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
    params = BuildParams()
    traj = load_trajectory_csv(str(csv_path))
    from roadgraph_builder.pipeline.build_graph import build_graph_from_trajectory
    graph = build_graph_from_trajectory(traj, params)
    with tempfile.TemporaryDirectory() as tmp:
        export_map_bundle(
            graph,
            traj.xy,
            str(csv_path),
            tmp,
            origin_lat=lat0,
            origin_lon=lon0,
            dataset_name="bench",
            lane_width_m=3.5,
        )


BENCHMARKS: dict[str, tuple] = {
    "polylines_to_graph_paris": (build_paris_graph, 1),
    "polylines_to_graph_10k_synth": (build_10k_synth, 1),
    "shortest_path_paris": (run_paris_routes_100, 1),
    "export_bundle_end_to_end": (export_bundle_paris, 1),
}


def run_benchmarks(warmup: bool = True) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for name, (fn, n_warmup) in BENCHMARKS.items():
        print(f"  {name} ...", file=sys.stderr, end="", flush=True)
        if warmup:
            for _ in range(n_warmup):
                try:
                    fn()
                except Exception as e:
                    print(f" [warmup error: {e}]", file=sys.stderr, end="")
        t0 = time.perf_counter()
        try:
            fn()
            elapsed = time.perf_counter() - t0
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f" ERROR: {e}", file=sys.stderr)
            results[name] = {"elapsed_s": elapsed, "error": str(e)}
            continue
        print(f" {elapsed:.3f}s", file=sys.stderr)
        results[name] = {"elapsed_s": elapsed}
    return results


def compare_to_baseline(results: dict, baseline: dict) -> list[str]:
    """Return list of regression messages (empty = no regressions)."""
    regressions: list[str] = []
    for name, cur in results.items():
        if name not in baseline:
            continue
        cur_t = cur.get("elapsed_s", 0.0)
        base_t = baseline[name].get("elapsed_s", 0.0)
        if base_t <= 0:
            continue
        ratio = cur_t / base_t
        if ratio >= 3.0:  # 200% worse = 3x baseline
            regressions.append(
                f"{name}: {cur_t:.3f}s vs baseline {base_t:.3f}s ({ratio:.1f}x, regression!)"
            )
    return regressions


def main() -> int:
    p = argparse.ArgumentParser(description="roadgraph_builder performance benchmarks.")
    p.add_argument(
        "--baseline",
        type=str,
        default=None,
        metavar="PATH",
        help="Saved baseline JSON to compare against. Exit 1 if any benchmark regresses > 200%%.",
    )
    p.add_argument(
        "--no-warmup",
        action="store_true",
        help="Skip warmup runs (faster but less stable).",
    )
    args = p.parse_args()

    print("Running benchmarks ...", file=sys.stderr)
    results = run_benchmarks(warmup=not args.no_warmup)
    print(json.dumps(results, indent=2))

    if args.baseline:
        bl_path = Path(args.baseline)
        if not bl_path.is_file():
            print(f"Baseline not found: {bl_path}", file=sys.stderr)
            return 1
        baseline = json.loads(bl_path.read_text(encoding="utf-8"))
        regressions = compare_to_baseline(results, baseline)
        if regressions:
            for msg in regressions:
                print(f"REGRESSION: {msg}", file=sys.stderr)
            return 1
        print("No regressions detected.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
