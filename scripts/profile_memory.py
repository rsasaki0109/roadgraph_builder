#!/usr/bin/env python3
"""Memory profiler for the build + export-bundle pipeline.

Uses ``tracemalloc`` to snapshot allocations before and after key pipeline
stages, then reports the top-20 allocators and overall peak RSS.  Also writes
a markdown summary to ``docs/memory_profile_v0.7.md``.

Usage::

    python scripts/profile_memory.py examples/osm_public_trackpoints.csv /tmp/profile_out

The script does NOT run on CI — it is a manual investigative tool.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import tracemalloc
from pathlib import Path

# Allow running directly from the repo root without installing.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _rss_kb() -> int:
    """Return current process peak RSS in kilobytes."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def profile_build_and_bundle(
    csv_path: str | Path,
    out_dir: str | Path,
    *,
    origin_lat: float = 48.86,
    origin_lon: float = 2.34,
    top_n: int = 20,
) -> dict:
    """Profile memory usage across the full build + export-bundle pipeline.

    Captures tracemalloc snapshots at four key points:
    1. After imports (baseline).
    2. After trajectory load.
    3. After graph build.
    4. After export-bundle.

    Returns a dict with top-N allocators (diff from baseline to post-bundle)
    and peak RSS numbers for each stage.

    Args:
        csv_path: Path to trajectory CSV (``timestamp, x, y`` format).
        out_dir: Directory to write the bundle artefacts (created if absent).
        origin_lat: WGS84 latitude of the meter-frame origin.
        origin_lon: WGS84 longitude of the meter-frame origin.
        top_n: Number of top allocations to report.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = Path(csv_path)

    # ---- Stage 0: imports ------------------------------------------------
    rss_0 = _rss_kb()
    tracemalloc.start()
    snap_0 = tracemalloc.take_snapshot()

    from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
    from roadgraph_builder.pipeline.build_graph import build_graph_from_csv, BuildParams
    from roadgraph_builder.io.export.bundle import export_map_bundle

    rss_imports = _rss_kb()

    # ---- Stage 1: load trajectory ----------------------------------------
    traj = load_trajectory_csv(str(csv_path))
    snap_1 = tracemalloc.take_snapshot()
    rss_1 = _rss_kb()

    # ---- Stage 2: build graph -------------------------------------------
    params = BuildParams()
    graph = build_graph_from_csv(str(csv_path), params)
    snap_2 = tracemalloc.take_snapshot()
    rss_2 = _rss_kb()

    # ---- Stage 3: export bundle -----------------------------------------
    export_map_bundle(
        graph,
        traj.xy,
        csv_path,
        out_dir,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        lane_width_m=3.5,
    )
    snap_3 = tracemalloc.take_snapshot()
    rss_3 = _rss_kb()

    current, peak_traced = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # ---- Build report ---------------------------------------------------
    top_stats = snap_3.compare_to(snap_0, "lineno")
    top_list = []
    for stat in top_stats[:top_n]:
        frame = stat.traceback[0]
        top_list.append(
            {
                "file": str(frame.filename),
                "lineno": frame.lineno,
                "size_bytes": stat.size,
                "size_diff_bytes": stat.size_diff,
                "count": stat.count,
                "count_diff": stat.count_diff,
            }
        )

    return {
        "csv_path": str(csv_path),
        "out_dir": str(out_dir),
        "rss_kb": {
            "after_imports": rss_imports,
            "after_trajectory_load": rss_1,
            "after_build": rss_2,
            "after_export_bundle": rss_3,
        },
        "tracemalloc_peak_kb": peak_traced // 1024,
        "top_allocations": top_list,
    }


def _render_markdown(result: dict) -> str:
    """Render profiling result as a Markdown table."""
    rss = result["rss_kb"]
    lines = [
        "# Memory profile — roadgraph_builder v0.7.0",
        "",
        f"Input: `{result['csv_path']}`",
        "",
        "## Peak RSS per pipeline stage",
        "",
        "| Stage | Peak RSS (KB) |",
        "| ----- | ------------- |",
        f"| After imports | {rss['after_imports']} |",
        f"| After trajectory load | {rss['after_trajectory_load']} |",
        f"| After graph build | {rss['after_build']} |",
        f"| After export-bundle | {rss['after_export_bundle']} |",
        "",
        f"tracemalloc peak: **{result['tracemalloc_peak_kb']} KB**",
        "",
        "## Top allocators (post-bundle vs import baseline)",
        "",
        "| File | Line | Size (B) | Δ Size (B) | Count |",
        "| ---- | ---- | -------- | ---------- | ----- |",
    ]
    for s in result["top_allocations"]:
        fname = s["file"].replace(str(Path.cwd()) + "/", "")
        lines.append(
            f"| `{fname}` | {s['lineno']} | {s['size_bytes']} |"
            f" {s['size_diff_bytes']:+d} | {s['count']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Profile build + export-bundle pipeline memory usage."
    )
    parser.add_argument("csv_path", type=Path, help="Trajectory CSV (timestamp, x, y).")
    parser.add_argument("out_dir", type=Path, help="Bundle output directory.")
    parser.add_argument("--origin-lat", type=float, default=48.86, help="Origin latitude.")
    parser.add_argument("--origin-lon", type=float, default=2.34, help="Origin longitude.")
    parser.add_argument("--top", type=int, default=20, help="Top-N allocations to report.")
    parser.add_argument(
        "--output-json", type=Path, default=None, help="Write JSON result to this file."
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/memory_profile_v0.7.md"),
        help="Write markdown report (default: docs/memory_profile_v0.7.md).",
    )
    args = parser.parse_args()

    if not args.csv_path.is_file():
        print(f"File not found: {args.csv_path}", file=sys.stderr)
        return 1

    print(f"Profiling: {args.csv_path} → {args.out_dir}", file=sys.stderr)
    result = profile_build_and_bundle(
        args.csv_path,
        args.out_dir,
        origin_lat=args.origin_lat,
        origin_lon=args.origin_lon,
        top_n=args.top,
    )

    rss = result["rss_kb"]
    print(f"Peak RSS after export-bundle: {rss['after_export_bundle']} KB "
          f"({rss['after_export_bundle'] / 1024:.1f} MB)")
    print(f"tracemalloc peak: {result['tracemalloc_peak_kb']} KB")

    print("\nTop allocators (post-bundle vs baseline):")
    for s in result["top_allocations"][:10]:
        fname = s["file"].replace(str(Path.cwd()) + "/", "")
        print(f"  {fname}:{s['lineno']}  size={s['size_bytes']}  Δ={s['size_diff_bytes']:+d}  count={s['count']}")

    if args.output_json:
        args.output_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"\nJSON: {args.output_json}")

    if args.output_md:
        md = _render_markdown(result)
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(md, encoding="utf-8")
        print(f"Markdown: {args.output_md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
