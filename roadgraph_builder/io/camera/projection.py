"""Pinhole image ↔ world-ground projection.

Given

- a :class:`CameraCalibration` (intrinsic K + camera-to-vehicle rigid mount),
- a per-image vehicle pose in the world meter frame (body FLU),
- a pixel ``(u, v)`` detection in the image,

:func:`pixel_to_ground` constructs the viewing ray in the world frame and
intersects it with the horizontal ground plane ``z = ground_z_m``. Returns the
``(x, y)`` of the intersection, ``None`` if the ray is parallel to the ground
or points *above* it (which happens for pixels above the horizon).

Math: the camera center in world frame is

    C_w = T_veh_world * t_camera_in_vehicle

and the ray direction in world frame is

    d_w = R_veh_world @ R_cam_in_vehicle @ R_body_to_optical^{-1} @ K^{-1} @ [u, v, 1]

which normalises so the ground-plane equation ``C_w.z + s * d_w.z == ground_z``
has a unique positive ``s`` when the pixel is below the horizon.

The helper :func:`project_image_detections` applies the full camera ->
vehicle -> world chain for every detection in an image-detections document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, cast

import numpy as np

from roadgraph_builder.io.camera.calibration import (
    _BODY_TO_OPTICAL,
    CameraCalibration,
    RigidTransform,
)


@dataclass
class GroundProjection:
    """One image-space detection, projected onto the ground plane."""

    image_id: str | None
    kind: str
    pixel: tuple[float, float]
    world_xy_m: tuple[float, float]
    confidence: float | None = None
    extras: dict[str, Any] | None = None


def pixel_to_ground(
    u: float,
    v: float,
    calibration: CameraCalibration,
    vehicle_pose: RigidTransform,
    *,
    ground_z_m: float = 0.0,
) -> tuple[float, float] | None:
    """Project one pixel onto the ground plane ``z = ground_z_m``.

    Returns ``(x, y)`` in the same world meter frame as ``vehicle_pose``, or
    ``None`` when the ray is parallel to the ground or hits at an infinite
    distance (pixel above the horizon).
    """
    # Pixel to normalised camera-frame ray (optical: +x right, +y down, +z fwd).
    # Runs the Brown-Conrady undistortion pass when the calibration carries
    # distortion coefficients; falls back to K^{-1}*[u,v,1] otherwise.
    xn, yn = calibration.intrinsic.undistort_pixel_to_normalized(u, v)
    ray_optical = np.array([xn, yn, 1.0], dtype=np.float64)
    # Optical to body-frame ray (so we can stack with the body-frame mount).
    ray_body_in_camera = np.linalg.inv(_BODY_TO_OPTICAL) @ ray_optical
    # Camera mount: rotate body-frame vector by the camera's body-frame rotation.
    ray_body = calibration.camera_to_vehicle.rotation @ ray_body_in_camera
    # Vehicle body to world.
    ray_world = vehicle_pose.rotation @ ray_body

    # Camera center in world frame: vehicle_pose applied to the camera
    # translation inside the vehicle.
    cam_center_body = calibration.camera_to_vehicle.translation
    cam_center_world = vehicle_pose.rotation @ cam_center_body + vehicle_pose.translation

    dz = ray_world[2]
    if abs(dz) < 1e-9:
        return None

    # ground_z = cam_center_world.z + s * dz ⇒ s = (ground_z - cz) / dz
    s = (ground_z_m - cam_center_world[2]) / dz
    if not np.isfinite(s) or s <= 0:
        return None

    hit = cam_center_world + s * ray_world
    return float(hit[0]), float(hit[1])


def load_image_detections_json(path) -> list[dict[str, Any]]:
    """Load an image-detections JSON, return the ``image_detections`` list.

    The expected shape is::

        {
          "format_version": 1,
          "image_detections": [
            {
              "image_id": "img_0001",
              "pose": {
                "translation_m": [x, y, z],
                "rotation_rpy_rad": [roll, pitch, yaw]
              },
              "detections": [
                {"kind": "lane_marking", "pixel": {"u": 640, "v": 800},
                 "value": "solid_white", "confidence": 0.9}
              ]
            }
          ]
        }
    """
    import json
    from pathlib import Path

    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("Image detections JSON root must be an object")
    items = raw.get("image_detections")
    if not isinstance(items, list):
        raise TypeError("Image detections JSON must have an 'image_detections' list")
    return [cast(dict[str, Any], it) for it in items if isinstance(it, dict)]


def _pose_from_dict(pose: dict[str, Any]) -> RigidTransform:
    t = pose.get("translation_m")
    if not isinstance(t, (list, tuple)) or len(t) != 3:
        raise ValueError("pose.translation_m must have length 3")
    tx = (float(t[0]), float(t[1]), float(t[2]))
    if "rotation_rpy_rad" in pose:
        rpy = pose["rotation_rpy_rad"]
        if len(rpy) != 3:
            raise ValueError("pose.rotation_rpy_rad must have length 3")
        return RigidTransform.from_rpy_xyz(
            (float(rpy[0]), float(rpy[1]), float(rpy[2])),
            tx,
        )
    if "rotation_matrix" in pose:
        R = np.asarray(pose["rotation_matrix"], dtype=np.float64)
        if R.shape != (3, 3):
            raise ValueError("pose.rotation_matrix must be 3x3")
        return RigidTransform(rotation=R, translation=np.asarray(tx, dtype=np.float64))
    return RigidTransform(rotation=np.eye(3), translation=np.asarray(tx, dtype=np.float64))


def project_image_detections(
    image_detections: Iterable[dict[str, Any]],
    calibration: CameraCalibration,
    *,
    ground_z_m: float = 0.0,
) -> list[GroundProjection]:
    """Project every pixel detection in every image to the ground plane.

    Skips detections where the ray points above the horizon (returns an
    empty list for that image without raising).
    """
    out: list[GroundProjection] = []
    for item in image_detections:
        pose = item.get("pose")
        if not isinstance(pose, dict):
            raise ValueError("each image_detections item must include 'pose'")
        veh_pose = _pose_from_dict(cast(dict[str, Any], pose))
        img_id = item.get("image_id")
        dets = item.get("detections") or []
        if not isinstance(dets, list):
            continue
        for det in dets:
            if not isinstance(det, dict):
                continue
            pixel = det.get("pixel")
            if not isinstance(pixel, dict):
                continue
            u = pixel.get("u")
            v = pixel.get("v")
            if not isinstance(u, (int, float)) or not isinstance(v, (int, float)):
                continue
            hit = pixel_to_ground(
                float(u), float(v),
                calibration,
                veh_pose,
                ground_z_m=ground_z_m,
            )
            if hit is None:
                continue
            kind = det.get("kind")
            if not isinstance(kind, str) or not kind:
                continue
            extras = {k: v for k, v in det.items() if k not in {"pixel", "kind", "confidence"}}
            conf = det.get("confidence")
            out.append(
                GroundProjection(
                    image_id=img_id if isinstance(img_id, str) else None,
                    kind=kind,
                    pixel=(float(u), float(v)),
                    world_xy_m=hit,
                    confidence=float(conf) if isinstance(conf, (int, float)) else None,
                    extras=extras or None,
                )
            )
    return out


__all__ = [
    "GroundProjection",
    "load_image_detections_json",
    "pixel_to_ground",
    "project_image_detections",
]
