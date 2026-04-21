"""Dataset-level batch CLI back-end — ``process-dataset`` command.

Iterates CSV files in a directory, calls ``export_map_bundle`` on each,
and aggregates results into a ``dataset_manifest.json``.

Per-file errors are isolated when ``continue_on_error=True`` (the default):
the failing file is recorded with ``status=failed`` + error message in the
manifest, and processing continues with the next file.  Exit code is 0 if
all files succeed, 1 if any failed (even with continue_on_error).

Output layout::

    output_dir/
        <stem_1>/    ← export-bundle output (nav/, sim/, lanelet/, manifest.json)
        <stem_2>/
        ...
        dataset_manifest.json  ← aggregate manifest with per-file status

``parallel > 1`` distributes work across ``parallel`` worker processes via
``concurrent.futures.ProcessPoolExecutor``.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, TextIO


def add_process_dataset_parser(
    sub,  # type: ignore[no-untyped-def]
    *,
    trajectory_dtype_choices: tuple[str, ...],
) -> None:
    """Register the ``process-dataset`` subcommand."""

    pd_cli = sub.add_parser(
        "process-dataset",
        help="Batch-process a directory of trajectory CSVs into per-file export-bundles.",
    )
    pd_cli.add_argument("input_dir", help="Directory containing trajectory CSV files.")
    pd_cli.add_argument("output_dir", help="Output directory (created if absent).")
    pd_cli.add_argument(
        "--origin-json",
        type=str,
        default=None,
        metavar="PATH",
        help="JSON with lat0, lon0 (shared origin for all CSVs in the dataset).",
    )
    pd_cli.add_argument(
        "--pattern",
        type=str,
        default="*.csv",
        metavar="GLOB",
        help="Glob pattern for trajectory files (default: '*.csv').",
    )
    pd_cli.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel worker processes (default: 1 = sequential).",
    )
    pd_cli.add_argument(
        "--continue-on-error",
        action="store_true",
        default=True,
        help="Continue processing other files if one fails (default: true).",
    )
    pd_cli.add_argument(
        "--no-continue-on-error",
        action="store_false",
        dest="continue_on_error",
        help="Abort on the first file error.",
    )
    pd_cli.add_argument(
        "--lane-width-m",
        type=float,
        default=3.5,
        metavar="M",
        help="HD-lite lane width for each bundle (meters, default 3.5).",
    )
    pd_cli.add_argument(
        "--dataset-name",
        type=str,
        default=None,
        metavar="NAME",
        help="Label prefix embedded in per-file GeoJSON/metadata (default: CSV stem).",
    )
    pd_cli.add_argument(
        "--trajectory-dtype",
        choices=trajectory_dtype_choices,
        default="float64",
        help=(
            "XY array dtype for trajectory loading (default float64). "
            "float32 is opt-in and may change exported coordinates slightly."
        ),
    )


def run_process_dataset(
    args: argparse.Namespace,
    *,
    process_dataset_func: Callable[..., dict[str, Any]] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``process-dataset`` from parsed args."""

    if process_dataset_func is None:
        process_dataset_func = process_dataset

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    if not input_dir.is_dir():
        print(f"Input directory not found: {input_dir}", file=err)
        return 1
    origin_json = Path(args.origin_json) if args.origin_json else None
    if origin_json is not None and not origin_json.is_file():
        print(f"Origin JSON not found: {origin_json}", file=err)
        return 1
    manifest = process_dataset_func(
        input_dir=input_dir,
        output_dir=output_dir,
        origin_json=origin_json,
        pattern=args.pattern,
        parallel=args.parallel,
        continue_on_error=args.continue_on_error,
        lane_width_m=args.lane_width_m,
        dataset_name_prefix=args.dataset_name,
        trajectory_xy_dtype=args.trajectory_dtype,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2), file=out)
    return 0 if manifest.get("failed_count", 0) == 0 else 1


def _process_single_file(
    csv_path: Path,
    bundle_dir: Path,
    *,
    origin_json: Path | None,
    lane_width_m: float,
    dataset_name: str,
    trajectory_xy_dtype: str = "float64",
) -> dict[str, Any]:
    """Run export_map_bundle on one CSV; return a per-file status dict.

    This function is designed to be called in a subprocess worker so it
    imports lazily and does not rely on shared state.

    Returns a dict with at minimum ``{"file": str, "status": "ok"|"failed"}``.
    On success adds ``graph_stats`` from the bundle manifest.  On failure adds
    ``"error": str``.
    """
    from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
    from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
    from roadgraph_builder.io.export.bundle import export_map_bundle
    from roadgraph_builder.utils.geo import load_wgs84_origin_json

    result: dict[str, Any] = {"file": str(csv_path), "status": "failed"}

    try:
        traj = load_trajectory_csv(csv_path, xy_dtype=trajectory_xy_dtype)
        params = BuildParams(trajectory_xy_dtype=trajectory_xy_dtype)
        graph = build_graph_from_trajectory(traj, params)

        lat0: float | None = None
        lon0: float | None = None
        if origin_json is not None:
            lat0, lon0 = load_wgs84_origin_json(origin_json)

        bundle_dir.mkdir(parents=True, exist_ok=True)
        export_map_bundle(
            graph,
            traj.xy,
            str(csv_path),
            str(bundle_dir),
            origin_lat=lat0 if lat0 is not None else 0.0,
            origin_lon=lon0 if lon0 is not None else 0.0,
            dataset_name=dataset_name,
            lane_width_m=lane_width_m,
        )

        # Read graph_stats from the written manifest if available.
        manifest_path = bundle_dir / "manifest.json"
        graph_stats: dict[str, Any] = {}
        if manifest_path.is_file():
            try:
                m = json.loads(manifest_path.read_text(encoding="utf-8"))
                graph_stats = m.get("graph_stats", {})
            except Exception:
                pass

        result["status"] = "ok"
        result["bundle_dir"] = str(bundle_dir)
        result["graph_stats"] = graph_stats
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()

    return result


def process_dataset(
    input_dir: Path,
    output_dir: Path,
    *,
    origin_json: Path | None = None,
    pattern: str = "*.csv",
    parallel: int = 1,
    continue_on_error: bool = True,
    lane_width_m: float = 3.5,
    dataset_name_prefix: str | None = None,
    trajectory_xy_dtype: str = "float64",
) -> dict[str, Any]:
    """Iterate CSV files, run export-bundle on each, aggregate stats.

    Args:
        input_dir: Directory containing trajectory CSV files.
        output_dir: Root output directory.  Per-file bundles land in
            ``output_dir/<csv_stem>/``.
        origin_json: Optional shared WGS84 origin JSON (lat0, lon0).  When
            ``None`` the origin defaults to (0, 0) and all coordinates are
            treated as relative meter-frame offsets.
        pattern: Glob pattern for CSV discovery (default ``"*.csv"``).
        parallel: Number of parallel worker processes.  ``1`` = sequential
            (safe for all platforms).  ``> 1`` uses
            ``concurrent.futures.ProcessPoolExecutor``.
        continue_on_error: When ``True`` (default), a failed file is logged
            and processing continues.  When ``False``, the first failure
            raises an exception and aborts.
        lane_width_m: HD-lite lane width forwarded to each bundle.
        dataset_name_prefix: Optional label prefix for each bundle's metadata.
            Defaults to the CSV stem.
        trajectory_xy_dtype: XY dtype forwarded to trajectory loading
            (``"float64"`` default; ``"float32"`` opt-in).

    Returns:
        Manifest dict with keys:
        - ``total_count``: number of CSV files discovered.
        - ``ok_count``: number that succeeded.
        - ``failed_count``: number that failed.
        - ``files``: list of per-file status dicts.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(input_dir.glob(pattern))
    if not csv_files:
        # Not an error — just an empty manifest.
        manifest: dict[str, Any] = {
            "total_count": 0,
            "ok_count": 0,
            "failed_count": 0,
            "files": [],
        }
        _write_manifest(output_dir, manifest)
        return manifest

    tasks = []
    for csv_path in csv_files:
        stem = csv_path.stem
        bundle_dir = output_dir / stem
        name = f"{dataset_name_prefix}_{stem}" if dataset_name_prefix else stem
        tasks.append((csv_path, bundle_dir, name))

    file_results: list[dict[str, Any]] = []

    if parallel > 1:
        futures = {}
        with ProcessPoolExecutor(max_workers=parallel) as executor:
            for csv_path, bundle_dir, name in tasks:
                fut = executor.submit(
                    _process_single_file,
                    csv_path,
                    bundle_dir,
                    origin_json=origin_json,
                    lane_width_m=lane_width_m,
                    dataset_name=name,
                    trajectory_xy_dtype=trajectory_xy_dtype,
                )
                futures[fut] = csv_path
            for fut in as_completed(futures):
                csv_path = futures[fut]
                try:
                    res = fut.result()
                except Exception as exc:
                    res = {
                        "file": str(csv_path),
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                if res["status"] == "failed" and not continue_on_error:
                    raise RuntimeError(
                        f"process-dataset: failed on {csv_path}: {res.get('error', '?')}"
                    )
                file_results.append(res)
    else:
        for csv_path, bundle_dir, name in tasks:
            res = _process_single_file(
                csv_path,
                bundle_dir,
                origin_json=origin_json,
                lane_width_m=lane_width_m,
                dataset_name=name,
                trajectory_xy_dtype=trajectory_xy_dtype,
            )
            if res["status"] == "failed" and not continue_on_error:
                raise RuntimeError(
                    f"process-dataset: failed on {csv_path}: {res.get('error', '?')}"
                )
            file_results.append(res)

    # Sort results to match input order.
    file_order = {str(csv): i for i, (csv, _, _) in enumerate(tasks)}
    file_results.sort(key=lambda r: file_order.get(r["file"], 9999))

    ok = [r for r in file_results if r["status"] == "ok"]
    failed = [r for r in file_results if r["status"] != "ok"]

    manifest = {
        "total_count": len(csv_files),
        "ok_count": len(ok),
        "failed_count": len(failed),
        "files": file_results,
    }
    _write_manifest(output_dir, manifest)
    return manifest


def _write_manifest(output_dir: Path, manifest: dict[str, Any]) -> None:
    """Write dataset_manifest.json to output_dir."""
    manifest_path = output_dir / "dataset_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
