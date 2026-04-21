"""CLI parser and command handlers for camera-related commands."""

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


def add_apply_camera_parser(sub) -> None:  # type: ignore[no-untyped-def]
    """Register the ``apply-camera`` subcommand."""

    cam = sub.add_parser(
        "apply-camera",
        help="Merge camera/perception JSON observations into attributes.hd.semantic_rules.",
    )
    cam.add_argument("input_json", help="Road graph JSON")
    cam.add_argument("detections_json", help="JSON with observations[] (edge_id, kind, ...)")
    cam.add_argument("output_json", help="Output JSON path")


def add_project_camera_parser(sub) -> None:  # type: ignore[no-untyped-def]
    """Register the ``project-camera`` subcommand."""

    pc = sub.add_parser(
        "project-camera",
        help=(
            "Project per-image pixel detections onto the ground plane using a "
            "pinhole camera + per-image vehicle pose, snap to the nearest graph "
            "edge, and write an edge-keyed camera_detections.json."
        ),
    )
    pc.add_argument("calibration_json", help="Camera calibration JSON (intrinsic + camera_to_vehicle).")
    pc.add_argument("image_detections_json", help="Per-image pixel detections JSON.")
    pc.add_argument("graph_json", help="Road graph JSON (same world meter frame as vehicle poses).")
    pc.add_argument("output_json", help="Output camera_detections.json path.")
    pc.add_argument(
        "--ground-z-m",
        type=float,
        default=0.0,
        metavar="M",
        help="Height of the assumed-flat ground plane in the world frame.",
    )
    pc.add_argument(
        "--max-edge-distance-m",
        type=float,
        default=5.0,
        metavar="M",
        help="Max perpendicular distance from a projected detection to a graph edge.",
    )


def add_detect_lane_markings_camera_parser(sub) -> None:  # type: ignore[no-untyped-def]
    """Register the ``detect-lane-markings-camera`` subcommand."""

    dlmc = sub.add_parser(
        "detect-lane-markings-camera",
        help=(
            "Detect lane markings from camera images using pure-NumPy HSV thresholds "
            "and project onto graph edges (3D2). Writes a camera_lanes.json."
        ),
    )
    dlmc.add_argument("graph_json", help="Road graph JSON (meter frame).")
    dlmc.add_argument("calibration_json", help="Camera calibration JSON (CameraCalibration format).")
    dlmc.add_argument("images_dir", help="Directory containing image files (.jpg/.png) named image_<id>.*")
    dlmc.add_argument("poses_json", help="JSON file with per-image poses: [{image_id, pose_x_m, pose_y_m, heading_rad}, ...]")
    dlmc.add_argument("--output", type=str, default="camera_lanes.json", metavar="PATH", help="Output JSON path (default: camera_lanes.json).")
    dlmc.add_argument("--white-threshold", type=int, default=200, metavar="V", help="Minimum value (0-255) for white lane detection.")
    dlmc.add_argument("--yellow-hue-lo", type=int, default=20, metavar="H", help="Lower bound of yellow hue range (0-360).")
    dlmc.add_argument("--yellow-hue-hi", type=int, default=40, metavar="H", help="Upper bound of yellow hue range (0-360).")
    dlmc.add_argument("--saturation-min", type=int, default=100, metavar="S", help="Minimum saturation (0-255) for yellow detection.")
    dlmc.add_argument("--min-line-length-px", type=int, default=30, metavar="PX", help="Minimum major-axis length (pixels) for lane candidates.")
    dlmc.add_argument("--max-edge-distance-m", type=float, default=3.5, metavar="M", help="Max lateral distance for edge snap.")


def projection_result_to_document(result) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Serialize project-camera result to the CLI JSON shape."""

    return {"format_version": 1, "observations": result.observations}


def camera_lanes_to_document(candidates) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Serialize projected camera lane candidates to the CLI JSON shape."""

    return {
        "camera_lanes": [
            {
                "edge_id": c.edge_id,
                "world_xy_m": list(c.world_xy_m),
                "kind": c.kind,
                "side": c.side,
                "confidence": c.confidence,
            }
            for c in candidates
        ]
    }


def find_image_file(images_dir: Path, image_id: str) -> Path | None:
    """Locate an image by id using the extensions supported by the CLI."""

    for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"):
        candidate = images_dir / f"{image_id}{ext}"
        if candidate.is_file():
            return candidate
    return None


def load_rgb_image(img_file: Path, *, stderr: TextIO | None = None):  # type: ignore[no-untyped-def]
    """Load an RGB image, using cv2 when available and a PNG fallback otherwise."""

    err = stderr if stderr is not None else sys.stderr
    try:
        import cv2  # type: ignore[import-not-found]

        bgr = cv2.imread(str(img_file))
        if bgr is None:
            return None
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except ImportError:
        try:
            import struct
            import zlib

            png = img_file.read_bytes()
            if png[:8] != b"\x89PNG\r\n\x1a\n":
                print(
                    f"detect-lane-markings-camera: cv2 not available; "
                    f"only PNG supported without it. Skipping {img_file.name}.",
                    file=err,
                )
                return None
            width = struct.unpack(">I", png[16:20])[0]
            height = struct.unpack(">I", png[20:24])[0]
            bit_depth = png[24]
            color_type = png[25]
            if bit_depth != 8 or color_type != 2:
                print("detect-lane-markings-camera: only 8-bit RGB PNG supported. Skipping.", file=err)
                return None

            offset = 8
            idat_data = b""
            while offset < len(png):
                length = struct.unpack(">I", png[offset:offset + 4])[0]
                chunk_type = png[offset + 4:offset + 8]
                if chunk_type == b"IDAT":
                    idat_data += png[offset + 8:offset + 8 + length]
                elif chunk_type == b"IEND":
                    break
                offset += 12 + length
            raw = zlib.decompress(idat_data)
            row_stride = 1 + width * 3

            import numpy as np

            pixels_flat = []
            for row_index in range(height):
                row_data = raw[row_index * row_stride + 1:(row_index + 1) * row_stride]
                pixels_flat.append(list(row_data))
            return np.array(pixels_flat, dtype=np.uint8).reshape(height, width, 3)
        except Exception as exc:
            print(f"detect-lane-markings-camera: failed to read {img_file.name}: {exc}", file=err)
            return None


def run_apply_camera(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    export_graph_json_func: Callable[..., object],
    load_detections_func: Callable[[str], object] | None = None,
    apply_detections_func: Callable[..., object] | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``apply-camera`` from parsed args."""

    err = stderr if stderr is not None else sys.stderr
    if load_detections_func is None:
        from roadgraph_builder.io.camera.detections import load_camera_detections_json

        load_detections_func = load_camera_detections_json
    if apply_detections_func is None:
        from roadgraph_builder.io.camera.detections import apply_camera_detections_to_graph

        apply_detections_func = apply_camera_detections_to_graph

    graph = load_graph(args.input_json)
    try:
        observations = load_detections_func(args.detections_json)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename or args.detections_json}", file=err)
        return 1
    apply_detections_func(graph, observations)
    export_graph_json_func(graph, args.output_json)
    return 0


def run_project_camera(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    load_calibration_func: Callable[[str], object] | None = None,
    load_items_func: Callable[[str], object] | None = None,
    project_func: Callable[..., object] | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``project-camera`` from parsed args."""

    err = stderr if stderr is not None else sys.stderr
    if load_calibration_func is None or load_items_func is None or project_func is None:
        from roadgraph_builder.io.camera import (
            load_camera_calibration,
            load_image_detections_json,
            project_image_detections_to_graph_edges,
        )

        load_calibration_func = load_calibration_func or load_camera_calibration
        load_items_func = load_items_func or load_image_detections_json
        project_func = project_func or project_image_detections_to_graph_edges

    try:
        calibration = load_calibration_func(args.calibration_json)
        items = load_items_func(args.image_detections_json)
        graph = load_graph(args.graph_json)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename or exc.args[0]}", file=err)
        return 1
    except (KeyError, ValueError, TypeError) as exc:
        print(f"{exc}", file=err)
        return 1

    result = project_func(
        items,
        calibration,
        graph,
        ground_z_m=args.ground_z_m,
        max_edge_distance_m=args.max_edge_distance_m,
    )
    Path(args.output_json).write_text(
        json.dumps(projection_result_to_document(result), indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {args.output_json}: {len(result.observations)} observations "
        f"(projected {result.projected_count}, "
        f"dropped_above_horizon {result.dropped_above_horizon}, "
        f"dropped_no_edge {result.dropped_no_edge}).",
        file=err,
    )
    return 0


def run_detect_lane_markings_camera(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    load_json: LoadJson,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``detect-lane-markings-camera`` from parsed args."""

    from roadgraph_builder.io.camera.calibration import CameraCalibration
    from roadgraph_builder.io.camera.lane_detection import (
        detect_lanes_from_image_rgb,
        project_camera_lanes_to_graph_edges,
    )

    err = stderr if stderr is not None else sys.stderr
    graph = load_graph(args.graph_json)
    calibration_raw = load_json(args.calibration_json)
    if not isinstance(calibration_raw, dict):
        print("detect-lane-markings-camera: calibration JSON must be an object.", file=err)
        return 1
    try:
        calibration = CameraCalibration.from_dict(calibration_raw)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"detect-lane-markings-camera: bad calibration: {exc}", file=err)
        return 1

    poses_raw = load_json(args.poses_json)
    if not isinstance(poses_raw, list):
        print("detect-lane-markings-camera: poses JSON must be a list.", file=err)
        return 1

    images_dir = Path(args.images_dir)
    if not images_dir.is_dir():
        print(f"Directory not found: {images_dir}", file=err)
        return 1

    all_candidates = []
    for pose_entry in poses_raw:
        if not isinstance(pose_entry, dict):
            continue
        image_id = str(pose_entry.get("image_id", ""))
        pose_x = float(pose_entry.get("pose_x_m", 0.0))
        pose_y = float(pose_entry.get("pose_y_m", 0.0))
        heading = float(pose_entry.get("heading_rad", 0.0))

        img_file = find_image_file(images_dir, image_id)
        if img_file is None:
            continue
        try:
            rgb_arr = load_rgb_image(img_file, stderr=err)
        except Exception as exc:
            print(f"detect-lane-markings-camera: error loading {img_file}: {exc}", file=err)
            continue
        if rgb_arr is None:
            continue

        lanes = detect_lanes_from_image_rgb(
            rgb_arr,
            white_threshold=args.white_threshold,
            yellow_hue_range=(args.yellow_hue_lo, args.yellow_hue_hi),
            saturation_min=args.saturation_min,
            min_line_length_px=args.min_line_length_px,
        )
        projected = project_camera_lanes_to_graph_edges(
            lanes,
            calibration,
            graph,
            pose_xy_m=(pose_x, pose_y),
            heading_rad=heading,
            max_edge_distance_m=args.max_edge_distance_m,
        )
        all_candidates.extend(projected)

    out_path = Path(args.output)
    out_path.write_text(json.dumps(camera_lanes_to_document(all_candidates), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}: {len(all_candidates)} camera lane candidates.", file=err)
    return 0
