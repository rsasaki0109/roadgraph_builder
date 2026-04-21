"""CLI parser and command handlers for LiDAR-related commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, TextIO, TYPE_CHECKING

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph


LoadGraph = Callable[[str], "Graph"]
LoadJson = Callable[[str], object]


def add_inspect_lidar_parser(sub) -> None:  # type: ignore[no-untyped-def]
    """Register the ``inspect-lidar`` subcommand."""

    ilas = sub.add_parser(
        "inspect-lidar",
        help="Print LAS public-header summary (version, point count, bbox, scale) as JSON.",
    )
    ilas.add_argument("input_las", help="Path to a .las file (public header is read; point records untouched).")


def add_fuse_lidar_parser(sub) -> None:  # type: ignore[no-untyped-def]
    """Register the ``fuse-lidar`` subcommand."""

    fuse = sub.add_parser(
        "fuse-lidar",
        help="Fit lane boundaries from a meter-frame point set (CSV or LAS) via per-edge proximity + binned median.",
    )
    fuse.add_argument("input_json", help="Road graph JSON")
    fuse.add_argument(
        "points_path",
        help="Point set in graph meters: CSV with x,y columns, LAS 1.0-1.4 (.las), or LAZ (.laz, requires 'laz' extra).",
    )
    fuse.add_argument("output_json", help="Output JSON path")
    fuse.add_argument(
        "--max-dist-m",
        type=float,
        default=5.0,
        metavar="M",
        help="Max perpendicular distance from a point to an edge centerline (meters).",
    )
    fuse.add_argument(
        "--bins",
        type=int,
        default=32,
        help="Number of bins along each edge for median aggregation.",
    )
    fuse.add_argument(
        "--ground-plane",
        action="store_true",
        default=False,
        help=(
            "3D mode: fit a ground plane via RANSAC to z-coordinate data and keep only "
            "points within --height-band-lo..--height-band-hi metres above the plane "
            "before lane-boundary fusion. Requires the point file to have x, y, z columns. "
            "Without this flag the behaviour is byte-identical to v0.6.0 (2D XY only)."
        ),
    )
    fuse.add_argument(
        "--height-band-lo",
        type=float,
        default=0.0,
        metavar="M",
        help="Lower bound of height band above ground plane (meters, default 0.0).",
    )
    fuse.add_argument(
        "--height-band-hi",
        type=float,
        default=0.3,
        metavar="M",
        help="Upper bound of height band above ground plane (meters, default 0.3).",
    )


def add_detect_lane_markings_parser(sub) -> None:  # type: ignore[no-untyped-def]
    """Register the ``detect-lane-markings`` subcommand."""

    dlm = sub.add_parser(
        "detect-lane-markings",
        help="Detect lane markings from LiDAR intensity peaks; write lane_markings.json.",
    )
    dlm.add_argument("graph_json", help="Road graph JSON.")
    dlm.add_argument("points_las", help="LAS/LAZ point cloud with intensity column (meter frame).")
    dlm.add_argument("--output", type=str, default="lane_markings.json", metavar="PATH", help="Output JSON path (default: lane_markings.json).")
    dlm.add_argument("--max-lateral-m", type=float, default=2.5, metavar="M", help="Max lateral distance from edge centerline to consider (m).")
    dlm.add_argument("--intensity-percentile", type=float, default=85.0, metavar="PCT", help="Percentile threshold for intensity peaks.")
    dlm.add_argument("--bin-m", type=float, default=1.0, metavar="M", help="Along-edge bin size (m).")
    dlm.add_argument("--min-points-per-bin", type=int, default=3, metavar="N", help="Min points per bin to form a cluster.")


def lane_marking_candidates_to_document(candidates) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Serialize LiDAR lane-marking candidates to the CLI JSON shape."""

    return {
        "candidates": [
            {
                "edge_id": c.edge_id,
                "side": c.side,
                "polyline_m": [list(pt) for pt in c.polyline_m],
                "intensity_median": c.intensity_median,
                "point_count": c.point_count,
            }
            for c in candidates
        ]
    }


def load_points_for_fusion(points_path: Path, *, use_ground_plane: bool):  # type: ignore[no-untyped-def]
    """Load a point cloud with the dimensionality required by ``fuse-lidar``."""

    if points_path.suffix.lower() in {".las", ".laz"}:
        if use_ground_plane:
            from roadgraph_builder.io.lidar.las import load_points_xyz_from_las

            return load_points_xyz_from_las(points_path)
        from roadgraph_builder.io.lidar.las import load_points_xy_from_las

        return load_points_xy_from_las(points_path)

    if use_ground_plane:
        from roadgraph_builder.io.lidar.points import load_points_xyz_csv

        return load_points_xyz_csv(points_path)
    from roadgraph_builder.io.lidar.points import load_points_xy_csv

    return load_points_xy_csv(points_path)


def load_las_xyzi_points(points_path: Path):  # type: ignore[no-untyped-def]
    """Load x/y/z/intensity from LAS/LAZ records for lane-marking detection."""

    import numpy as np
    from roadgraph_builder.io.lidar.las import read_las_header

    header = read_las_header(points_path)
    record_length = header.point_data_record_length
    point_count = header.point_count
    with points_path.open("rb") as fh:
        fh.seek(header.offset_to_point_data)
        blob = fh.read(record_length * point_count)
    buf = np.frombuffer(blob, dtype=np.uint8).reshape(point_count, record_length)
    xi = buf[:, 0:4].copy().view(np.int32).reshape(point_count)
    yi = buf[:, 4:8].copy().view(np.int32).reshape(point_count)
    zi = buf[:, 8:12].copy().view(np.int32).reshape(point_count)
    intensity = buf[:, 12:14].copy().view(np.uint16).reshape(point_count)
    sx, sy, sz = header.scale
    ox, oy, oz = header.offset
    points = np.empty((point_count, 4), dtype=np.float64)
    points[:, 0] = xi.astype(np.float64) * sx + ox
    points[:, 1] = yi.astype(np.float64) * sy + oy
    points[:, 2] = zi.astype(np.float64) * sz + oz
    points[:, 3] = intensity.astype(np.float64)
    return points


def run_inspect_lidar(
    args: argparse.Namespace,
    *,
    read_header_func: Callable[[Path], object] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``inspect-lidar`` from parsed args."""

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    path = Path(args.input_las)
    if not path.is_file():
        print(f"File not found: {path}", file=err)
        return 1
    if read_header_func is None:
        from roadgraph_builder.io.lidar.las import read_las_header

        read_header_func = read_las_header
    try:
        header = read_header_func(path)
    except ValueError as exc:
        print(f"{path}: {exc}", file=err)
        return 1
    print(json.dumps(header.to_summary(), ensure_ascii=False, indent=2), file=out)
    return 0


def run_fuse_lidar(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    export_graph_json_func: Callable[..., object],
    load_points_func: Callable[..., object] | None = None,
    fuse_2d_func: Callable[..., object] | None = None,
    fuse_3d_func: Callable[..., object] | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``fuse-lidar`` from parsed args."""

    err = stderr if stderr is not None else sys.stderr
    graph = load_graph(args.input_json)
    points_path = Path(args.points_path)
    if not points_path.is_file():
        print(f"File not found: {points_path}", file=err)
        return 1

    use_ground_plane = getattr(args, "ground_plane", False)
    try:
        loader = load_points_func or load_points_for_fusion
        points = loader(points_path, use_ground_plane=use_ground_plane)
    except ValueError as exc:
        print(f"{points_path}: {exc}", file=err)
        return 1
    except ImportError as exc:
        print(f"{points_path}: {exc}", file=err)
        return 1

    if use_ground_plane:
        if points.ndim != 2 or points.shape[1] < 3:
            print(
                f"{points_path}: --ground-plane requires x,y,z columns; got shape {points.shape}",
                file=err,
            )
            return 1
        if fuse_3d_func is None:
            from roadgraph_builder.hd.lidar_fusion import fuse_lane_boundaries_3d

            fuse_3d_func = fuse_lane_boundaries_3d
        fuse_3d_func(
            graph,
            points,
            height_band_m=(args.height_band_lo, args.height_band_hi),
            max_dist_m=args.max_dist_m,
            bins=args.bins,
        )
    else:
        if fuse_2d_func is None:
            from roadgraph_builder.hd.lidar_fusion import fuse_lane_boundaries_from_points

            fuse_2d_func = fuse_lane_boundaries_from_points
        fuse_2d_func(graph, points, max_dist_m=args.max_dist_m, bins=args.bins)

    export_graph_json_func(graph, args.output_json)
    return 0


def run_detect_lane_markings(
    args: argparse.Namespace,
    *,
    load_json: LoadJson,
    load_points_func: Callable[[Path], object] | None = None,
    detect_func: Callable[..., object] | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``detect-lane-markings`` from parsed args."""

    err = stderr if stderr is not None else sys.stderr
    graph_data = load_json(args.graph_json)
    if not isinstance(graph_data, dict):
        print("detect-lane-markings: graph JSON root must be an object.", file=err)
        return 1
    points_path = Path(args.points_las)
    if not points_path.is_file():
        print(f"File not found: {points_path}", file=err)
        return 1
    if points_path.suffix.lower() not in {".las", ".laz"}:
        print(f"detect-lane-markings: only LAS/LAZ files are supported, got {points_path.suffix}", file=err)
        return 1

    try:
        loader = load_points_func or load_las_xyzi_points
        points_xyzi = loader(points_path)
    except ValueError as exc:
        print(f"{points_path}: {exc}", file=err)
        return 1

    if detect_func is None:
        from roadgraph_builder.io.lidar.lane_marking import detect_lane_markings

        detect_func = detect_lane_markings
    candidates = detect_func(
        graph_data,
        points_xyzi,
        max_lateral_m=args.max_lateral_m,
        intensity_percentile=args.intensity_percentile,
        along_edge_bin_m=args.bin_m,
        min_points_per_bin=args.min_points_per_bin,
    )
    out_path = Path(args.output)
    out_path.write_text(json.dumps(lane_marking_candidates_to_document(candidates), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}: {len(candidates)} candidates.", file=err)
    return 0
