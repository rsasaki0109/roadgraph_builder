#!/usr/bin/env python3
"""Generate a self-contained camera-pipeline demo dataset.

Picks a short simulated drive of a vehicle with a forward-facing wide-angle
camera (with Brown-Conrady distortion), places a handful of ground-truth
world-frame features (lane marks, a stop line, a speed-limit sign location),
forward-projects them through the simulated camera into pixel coordinates,
rounds to the pixel grid, and writes::

  examples/demo_camera_calibration.json
  examples/demo_image_detections.json

This is what a real "detector → annotations" feed looks like to the
``project-camera`` CLI. Running::

    roadgraph_builder project-camera \\
      examples/demo_camera_calibration.json \\
      examples/demo_image_detections.json \\
      GRAPH.json OUT.json

should recover the original world points to within sub-meter accuracy (the
round-to-pixel step introduces the only material error).

The generator uses ``cv2.projectPoints`` when OpenCV is installed so the
forward distortion matches our ``CameraIntrinsic.undistort_pixel_to_normalized``
inverse bit-for-bit (cross-validation path). Falls back to a pure-numpy
distortion forward model when ``cv2`` isn't present.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from roadgraph_builder.io.camera.calibration import (
    CameraCalibration,
    CameraIntrinsic,
    RigidTransform,
    rpy_to_matrix,
)


_BODY_TO_OPTICAL = np.array(
    [
        [0.0, -1.0, 0.0],
        [0.0, 0.0, -1.0],
        [1.0, 0.0, 0.0],
    ],
    dtype=np.float64,
)


def _world_to_pixel_numpy(
    world_point: np.ndarray,
    calibration: CameraCalibration,
    vehicle_pose: RigidTransform,
) -> tuple[float, float] | None:
    """Forward-project one world-frame point into pixel coordinates.

    Applies the same distortion model that :meth:`CameraIntrinsic.
    undistort_pixel_to_normalized` inverts. Returns ``None`` when the point is
    behind the camera.
    """
    # World -> vehicle body
    body = vehicle_pose.inverse().apply(world_point.reshape(1, 3))[0]
    # Body -> camera body (undo the mount).
    cam_body = calibration.camera_to_vehicle.inverse().apply(body.reshape(1, 3))[0]
    # Camera body -> optical frame (+x right, +y down, +z fwd).
    optical = _BODY_TO_OPTICAL @ cam_body
    if optical[2] <= 1e-9:
        return None
    x = optical[0] / optical[2]
    y = optical[1] / optical[2]
    k1, k2, p1, p2, k3 = calibration.intrinsic.distortion_array
    r2 = x * x + y * y
    radial = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
    xd = x * radial + 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x)
    yd = y * radial + p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y
    u = calibration.intrinsic.fx * xd + calibration.intrinsic.cx
    v = calibration.intrinsic.fy * yd + calibration.intrinsic.cy
    return float(u), float(v)


def _world_to_pixel_cv2(
    world_point: np.ndarray,
    calibration: CameraCalibration,
    vehicle_pose: RigidTransform,
) -> tuple[float, float] | None:
    """OpenCV-backed forward projection used when ``cv2`` is importable.

    The composed world-to-optical rotation and translation are converted to
    the OpenCV rvec/tvec form and fed through ``cv2.projectPoints``.
    """
    import cv2  # local import so the generator still runs without OpenCV.

    # World -> vehicle, then vehicle -> camera mount, then body -> optical.
    T_veh_world = vehicle_pose
    T_cam_veh = calibration.camera_to_vehicle
    # World-to-vehicle rotation + translation:
    # X_veh = R_veh_world^T (X_world - t_veh_world)
    Rw = T_veh_world.rotation
    tw = T_veh_world.translation
    Rv = T_cam_veh.rotation
    tv = T_cam_veh.translation
    # Camera optical frame coordinates of world_point:
    # X_body_veh = R_veh_world^T * (X_world - t_veh_world)
    # X_body_cam = R_cam_veh^T * (X_body_veh - t_cam_veh)
    # X_optical = BODY_TO_OPTICAL @ X_body_cam
    Xvb = Rw.T @ (world_point - tw)
    Xcb = Rv.T @ (Xvb - tv)
    Xopt = _BODY_TO_OPTICAL @ Xcb
    if Xopt[2] <= 1e-9:
        return None
    image_points, _ = cv2.projectPoints(
        np.array([[Xopt]], dtype=np.float64).reshape(-1, 1, 3),
        np.zeros((3, 1), dtype=np.float64),
        np.zeros((3, 1), dtype=np.float64),
        calibration.intrinsic.matrix,
        calibration.intrinsic.distortion_array,
    )
    u, v = image_points.reshape(-1, 2)[0]
    return float(u), float(v)


def world_to_pixel(world_point, calibration, vehicle_pose):
    """Pick the OpenCV backend when possible; fall back to the numpy path."""
    try:
        return _world_to_pixel_cv2(np.asarray(world_point, dtype=np.float64), calibration, vehicle_pose)
    except ImportError:
        return _world_to_pixel_numpy(np.asarray(world_point, dtype=np.float64), calibration, vehicle_pose)


# A short simulated drive: four vehicle poses 5 m apart along +x with the
# camera always facing forward. At each pose we observe a handful of nearby
# ground-truth features.
DEMO_VEHICLE_POSES = [
    {"image_id": "demo_0001", "xy": (0.0, 0.0), "yaw_rad": 0.0},
    {"image_id": "demo_0002", "xy": (5.0, 0.0), "yaw_rad": 0.0},
    {"image_id": "demo_0003", "xy": (10.0, 0.0), "yaw_rad": 0.0},
    {"image_id": "demo_0004", "xy": (15.0, 0.0), "yaw_rad": 0.0},
]

# World-frame ground-truth features. z=0 since our graph lives on the ground plane.
DEMO_FEATURES = [
    {"world": (10.0, 1.75, 0.0), "kind": "lane_marking", "value": "solid_white_left"},
    {"world": (10.0, -1.75, 0.0), "kind": "lane_marking", "value": "solid_white_right"},
    {"world": (18.0, 0.0, 0.0), "kind": "stop_line", "value": "stop"},
    {"world": (20.0, 3.5, 0.0), "kind": "speed_limit", "value_kmh": 50},
    {"world": (20.0, -3.5, 0.0), "kind": "speed_limit", "value_kmh": 50},
]


def build_demo_calibration() -> CameraCalibration:
    """Forward-facing wide-angle camera with realistic barrel distortion."""
    intr = CameraIntrinsic(
        fx=900.0,
        fy=900.0,
        cx=640.0,
        cy=400.0,
        image_width=1280,
        image_height=800,
        distortion=(-0.27, 0.09, 0.0005, -0.0003, -0.02),
    )
    mount = RigidTransform.from_rpy_xyz((0.0, 0.0, 0.0), (0.0, 0.0, 1.5))
    return CameraCalibration(intrinsic=intr, camera_to_vehicle=mount)


def build_demo_dataset(out_dir: Path) -> tuple[Path, Path]:
    calib = build_demo_calibration()
    images: list[dict] = []
    for pose_meta in DEMO_VEHICLE_POSES:
        x, y = pose_meta["xy"]
        veh_pose = RigidTransform.from_rpy_xyz(
            (0.0, 0.0, pose_meta["yaw_rad"]), (x, y, 0.0)
        )
        detections: list[dict] = []
        for feat in DEMO_FEATURES:
            pixel = world_to_pixel(feat["world"], calib, veh_pose)
            if pixel is None:
                continue
            u, v = pixel
            if u < 0 or v < 0 or u > calib.intrinsic.image_width or v > calib.intrinsic.image_height:
                continue
            entry = {
                "kind": feat["kind"],
                "pixel": {"u": round(u, 1), "v": round(v, 1)},
                "_world_ground_truth_m": list(feat["world"]),
            }
            if "value" in feat:
                entry["value"] = feat["value"]
            if "value_kmh" in feat:
                entry["value_kmh"] = feat["value_kmh"]
            detections.append(entry)
        if detections:
            images.append(
                {
                    "image_id": pose_meta["image_id"],
                    "pose": {
                        "translation_m": [x, y, 0.0],
                        "rotation_rpy_rad": [0.0, 0.0, pose_meta["yaw_rad"]],
                    },
                    "detections": detections,
                }
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    calib_path = out_dir / "demo_camera_calibration.json"
    img_path = out_dir / "demo_image_detections.json"
    calib_path.write_text(json.dumps(calib.to_dict(), indent=2) + "\n", encoding="utf-8")
    img_path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "_comment": (
                    "Synthetic but realistic demo: ground-truth world points forward-projected "
                    "through a wide-angle camera with Brown-Conrady distortion. Each detection "
                    "carries its _world_ground_truth_m so tests can verify project-camera recovers "
                    "it. Regenerate with scripts/generate_camera_demo.py."
                ),
                "image_detections": images,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return calib_path, img_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("examples"),
        help="Output directory (default: examples/).",
    )
    args = ap.parse_args()
    calib_path, img_path = build_demo_dataset(args.out_dir)
    print(f"Wrote {calib_path} and {img_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
