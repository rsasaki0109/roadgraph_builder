"""Camera calibration model: pinhole intrinsic + rigid 6-DoF extrinsic.

JSON / in-memory dataclasses. The ``camera_to_vehicle`` extrinsic describes the
*constant* mount of the camera on the vehicle (rigid). Per-image vehicle poses
are carried separately by the image-detections file — combined at projection
time to get world-to-camera for each frame.

All rotations use intrinsic roll-pitch-yaw (RPY / Tait-Bryan) in radians,
composed as ``R = Rz(yaw) @ Ry(pitch) @ Rx(roll)``. This matches common
automotive conventions (e.g. ROS REP-103) where ``yaw`` is around the body
vertical axis and positive angles follow the right-hand rule.

Body frame (FLU): ``+x`` forward, ``+y`` left, ``+z`` up. The camera frame
convention is the classic optical model: ``+x`` right-in-image, ``+y`` down-in-
image, ``+z`` forward-into-scene. ``camera_to_vehicle`` is expressed in the
body frame — it tells you where the camera sits and how it's oriented on the
vehicle, including the optical-axis reorientation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np


@dataclass(frozen=True)
class CameraIntrinsic:
    """Pinhole camera intrinsic parameters with optional Brown-Conrady distortion.

    ``distortion`` holds the OpenCV-order 5-coefficient vector
    ``(k1, k2, p1, p2, k3)`` — ``k1 k2 k3`` are radial, ``p1 p2`` are
    tangential. An empty tuple (the default) means "undistorted pinhole".

    The distortion model matches ``cv2.undistortPoints`` with
    ``R=None, P=None``: given normalised undistorted coordinates ``(x, y)`` the
    distorted normalised coordinates are::

        r2 = x*x + y*y
        radial = 1 + k1*r2 + k2*r2**2 + k3*r2**3
        x_d = x * radial + 2*p1*x*y + p2*(r2 + 2*x*x)
        y_d = y * radial + p1*(r2 + 2*y*y) + 2*p2*x*y

    :meth:`undistort_pixel_to_normalized` inverts this (fixed-point iteration)
    to recover the undistorted ray direction ``(x, y, 1)`` for a distorted
    pixel ``(u, v)``. For the no-distortion case it degenerates to the plain
    ``K^{-1} * [u, v, 1]``.
    """

    fx: float
    fy: float
    cx: float
    cy: float
    image_width: int = 0  # 0 means unknown / any
    image_height: int = 0
    distortion: tuple[float, ...] = ()

    @property
    def matrix(self) -> np.ndarray:
        """Return the 3x3 K matrix."""
        return np.array(
            [
                [self.fx, 0.0, self.cx],
                [0.0, self.fy, self.cy],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )

    @property
    def distortion_array(self) -> np.ndarray:
        """Always return a length-5 ``(k1, k2, p1, p2, k3)`` vector (zero-padded)."""
        d = list(self.distortion)
        while len(d) < 5:
            d.append(0.0)
        return np.asarray(d[:5], dtype=np.float64)

    def undistort_pixel_to_normalized(
        self, u: float, v: float, *, max_iters: int = 12, tol: float = 1e-9
    ) -> tuple[float, float]:
        """Pixel ``(u, v)`` → undistorted normalized camera coordinate ``(x, y)``.

        Returns ``((u - cx) / fx, (v - cy) / fy)`` when ``distortion`` is empty
        or all-zero. Otherwise runs a fixed-point iteration on the Brown-
        Conrady model. Converges in ~5 iterations for realistic wide-angle
        distortion; ``max_iters`` guards against divergent cases.
        """
        xd = (u - self.cx) / self.fx
        yd = (v - self.cy) / self.fy
        if not any(self.distortion):
            return xd, yd
        k1, k2, p1, p2, k3 = self.distortion_array
        x = xd
        y = yd
        for _ in range(max_iters):
            r2 = x * x + y * y
            radial = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
            dx_tang = 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x)
            dy_tang = p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y
            x_next = (xd - dx_tang) / radial
            y_next = (yd - dy_tang) / radial
            if abs(x_next - x) < tol and abs(y_next - y) < tol:
                x, y = x_next, y_next
                break
            x, y = x_next, y_next
        return x, y

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
        }
        if self.image_width or self.image_height:
            out["image_size"] = {"width": self.image_width, "height": self.image_height}
        if any(self.distortion):
            d = self.distortion_array.tolist()
            out["distortion"] = {"k1": d[0], "k2": d[1], "p1": d[2], "p2": d[3], "k3": d[4]}
        return out

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CameraIntrinsic":
        for k in ("fx", "fy", "cx", "cy"):
            if k not in data:
                raise KeyError(f"intrinsic.{k} required")
        size = data.get("image_size") or {}
        dist_raw = data.get("distortion")
        distortion: tuple[float, ...] = ()
        if isinstance(dist_raw, dict):
            distortion = (
                float(dist_raw.get("k1", 0.0)),
                float(dist_raw.get("k2", 0.0)),
                float(dist_raw.get("p1", 0.0)),
                float(dist_raw.get("p2", 0.0)),
                float(dist_raw.get("k3", 0.0)),
            )
        elif isinstance(dist_raw, (list, tuple)):
            distortion = tuple(float(c) for c in dist_raw[:5])
        return CameraIntrinsic(
            fx=float(data["fx"]),
            fy=float(data["fy"]),
            cx=float(data["cx"]),
            cy=float(data["cy"]),
            image_width=int(size.get("width", 0)),
            image_height=int(size.get("height", 0)),
            distortion=distortion,
        )


def rpy_to_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """Intrinsic RPY → 3x3 rotation matrix ``R = Rz(yaw) @ Ry(pitch) @ Rx(roll)``."""
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cr, -sr], [0.0, sr, cr]])
    ry = np.array([[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]])
    rz = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]])
    return rz @ ry @ rx


@dataclass(frozen=True)
class RigidTransform:
    """Rigid 6-DoF transform: rotate + translate."""

    rotation: np.ndarray  # 3x3
    translation: np.ndarray  # (3,)

    @staticmethod
    def from_rpy_xyz(rpy_rad: tuple[float, float, float], xyz_m: tuple[float, float, float]) -> "RigidTransform":
        R = rpy_to_matrix(*rpy_rad)
        t = np.asarray(xyz_m, dtype=np.float64)
        return RigidTransform(rotation=R, translation=t)

    def inverse(self) -> "RigidTransform":
        inv_R = self.rotation.T
        return RigidTransform(rotation=inv_R, translation=-inv_R @ self.translation)

    def __matmul__(self, other: "RigidTransform") -> "RigidTransform":
        R = self.rotation @ other.rotation
        t = self.rotation @ other.translation + self.translation
        return RigidTransform(rotation=R, translation=t)

    def apply(self, points: np.ndarray) -> np.ndarray:
        """Apply to an (N, 3) array; returns (N, 3)."""
        return (points @ self.rotation.T) + self.translation


# Reorient from body FLU (+x fwd, +y left, +z up) to optical (+x right, +y
# down, +z forward). Applied AFTER the body-frame RPY so a camera mounted
# straight ahead with rpy=(0,0,0) looks forward.
_BODY_TO_OPTICAL = np.array(
    [
        [0.0, -1.0, 0.0],
        [0.0, 0.0, -1.0],
        [1.0, 0.0, 0.0],
    ],
    dtype=np.float64,
)


@dataclass(frozen=True)
class CameraCalibration:
    """Intrinsic + rigid ``camera_to_vehicle`` mount.

    The rotation/translation in ``camera_to_vehicle`` describe the camera's
    pose expressed in the vehicle body frame (FLU). The conversion to the
    optical camera frame is handled inside :class:`PinholeCamera`, not here,
    so the calibration file stays in a frame users can reason about.
    """

    intrinsic: CameraIntrinsic
    camera_to_vehicle: RigidTransform

    def to_dict(self) -> dict[str, Any]:
        # We cannot round-trip an arbitrary rotation matrix back to RPY in
        # general, so the writer always stores whatever was passed in — we
        # round-trip only when the rotation started as RPY. Expose the matrix
        # verbatim for fidelity.
        return {
            "intrinsic": self.intrinsic.to_dict(),
            "camera_to_vehicle": {
                "rotation_matrix": self.camera_to_vehicle.rotation.tolist(),
                "translation_m": self.camera_to_vehicle.translation.tolist(),
            },
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CameraCalibration":
        if "intrinsic" not in data:
            raise KeyError("calibration.intrinsic required")
        intr = CameraIntrinsic.from_dict(cast(dict[str, Any], data["intrinsic"]))

        ext_raw = data.get("camera_to_vehicle") or {}
        ext = cast(dict[str, Any], ext_raw)
        tx = ext.get("translation_m", [0.0, 0.0, 0.0])
        t = np.asarray(tx, dtype=np.float64)
        if t.shape != (3,):
            raise ValueError("camera_to_vehicle.translation_m must have length 3")

        if "rotation_matrix" in ext:
            R = np.asarray(ext["rotation_matrix"], dtype=np.float64)
            if R.shape != (3, 3):
                raise ValueError("camera_to_vehicle.rotation_matrix must be 3x3")
        elif "rotation_rpy_rad" in ext:
            rpy = ext["rotation_rpy_rad"]
            if len(rpy) != 3:
                raise ValueError("rotation_rpy_rad must have length 3")
            R = rpy_to_matrix(float(rpy[0]), float(rpy[1]), float(rpy[2]))
        else:
            R = np.eye(3)
        return CameraCalibration(
            intrinsic=intr,
            camera_to_vehicle=RigidTransform(rotation=R, translation=t),
        )


def load_camera_calibration(path: str | Path) -> CameraCalibration:
    """Read a JSON calibration file."""
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(f"Calibration JSON root must be an object: {p}")
    return CameraCalibration.from_dict(cast(dict[str, Any], raw))


__all__ = [
    "CameraCalibration",
    "CameraIntrinsic",
    "RigidTransform",
    "load_camera_calibration",
    "rpy_to_matrix",
    # exposed for tests:
    "_BODY_TO_OPTICAL",
]
