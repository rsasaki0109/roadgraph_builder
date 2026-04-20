"""Camera-only lane detection (3D2).

Pure-NumPy image-space lane detection without ML.  The algorithm converts an
RGB image to HSV, applies colour thresholds to extract white and yellow lane
markings, performs connected-component labelling, keeps only components that
are elongated (aspect ratio filter), and returns a list of pixel-space
``LinePixel`` objects describing each candidate.

The second entry point, ``project_camera_lanes_to_graph_edges``, projects those
pixel-space lanes onto the ground plane (using the existing
:func:`roadgraph_builder.io.camera.projection.pixel_to_ground` path) and snaps
each projected line to the nearest graph edge, producing
``LaneMarkingCandidate`` objects compatible with the existing camera-detection
consumer chain.

No external dependencies beyond NumPy are required at runtime.  If ``cv2`` is
importable it is used only for validation / debugging purposes — the primary
code path never calls it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from roadgraph_builder.io.camera.calibration import CameraCalibration, RigidTransform
    from roadgraph_builder.core.graph.graph import Graph


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class LinePixel:
    """A candidate lane-marking region in pixel coordinates.

    Attributes:
        pixels: (N, 2) array of (row, col) pixel indices belonging to this
            connected component.
        kind: Detected colour — ``"white"`` or ``"yellow"``.
        bbox: (row_min, col_min, row_max, col_max) bounding box.
        length_px: Estimated length of the component along its major axis
            (approx sqrt of the bbox diagonal).
    """

    pixels: np.ndarray  # (N, 2) int
    kind: str  # "white" | "yellow"
    bbox: tuple[int, int, int, int]  # row_min, col_min, row_max, col_max
    length_px: float


@dataclass
class LaneMarkingCandidate:
    """A lane-marking candidate in world coordinates, snapped to a graph edge.

    Attributes:
        edge_id: Graph edge this marking was snapped to, or ``None`` if no edge
            is close enough.
        world_xy_m: (x, y) projected world position (midpoint of the component).
        kind: Colour class — ``"white"`` or ``"yellow"``.
        side: ``"left"``, ``"right"``, or ``"unknown"`` relative to the edge.
        confidence: Rough confidence score [0, 1] based on component length.
    """

    edge_id: str | None
    world_xy_m: tuple[float, float]
    kind: str
    side: str
    confidence: float


# ---------------------------------------------------------------------------
# Pure-NumPy helpers
# ---------------------------------------------------------------------------


def _rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    """Convert an HxWx3 uint8 RGB image to HSV (float32, H∈[0,360), S∈[0,1], V∈[0,1]).

    This is a pure-NumPy implementation of the standard HSV conversion,
    independent of OpenCV or Pillow.  Vectorised over all pixels.
    """
    rgb_f = rgb.astype(np.float32) / 255.0
    r, g, b = rgb_f[..., 0], rgb_f[..., 1], rgb_f[..., 2]

    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin

    # Value
    v = cmax

    # Saturation
    s = np.where(cmax > 0, delta / cmax, 0.0).astype(np.float32)

    # Hue
    h = np.zeros_like(r)
    eps = 1e-7

    mask_r = (cmax == r) & (delta > eps)
    mask_g = (cmax == g) & (delta > eps)
    mask_b = (cmax == b) & (delta > eps)

    h[mask_r] = ((g[mask_r] - b[mask_r]) / delta[mask_r]) % 6.0
    h[mask_g] = (b[mask_g] - r[mask_g]) / delta[mask_g] + 2.0
    h[mask_b] = (r[mask_b] - g[mask_b]) / delta[mask_b] + 4.0

    h = (h * 60.0) % 360.0

    return np.stack([h, s, v], axis=-1)


def _connected_components_2d(mask: np.ndarray) -> np.ndarray:
    """Simple 4-connected component labelling using an iterative union-find approach.

    Works on a boolean (H, W) array.  Returns an (H, W) int32 label array
    where 0 = background, 1..N = component ids.

    Uses a stack-based flood fill for each unlabelled foreground pixel.
    Sufficient for small–medium images; avoids scipy / cv2 dependency.
    """
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    current_label = 0

    for start_r in range(h):
        for start_c in range(w):
            if not mask[start_r, start_c] or labels[start_r, start_c] != 0:
                continue
            current_label += 1
            stack = [(start_r, start_c)]
            while stack:
                r, c = stack.pop()
                if r < 0 or r >= h or c < 0 or c >= w:
                    continue
                if not mask[r, c] or labels[r, c] != 0:
                    continue
                labels[r, c] = current_label
                stack.extend([(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)])
    return labels


def _fast_connected_components(mask: np.ndarray, min_size: int) -> list[np.ndarray]:
    """Wrapper around _connected_components_2d that uses numpy tricks for large masks.

    Returns a list of (N, 2) int arrays of (row, col) for each component whose
    size exceeds ``min_size``.
    """
    labels = _connected_components_2d(mask)
    n_labels = int(labels.max())
    components: list[np.ndarray] = []
    for lbl in range(1, n_labels + 1):
        pixels = np.argwhere(labels == lbl)
        if len(pixels) >= min_size:
            components.append(pixels)
    return components


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_lanes_from_image_rgb(
    rgb: np.ndarray,
    *,
    white_threshold: int = 200,
    yellow_hue_range: tuple[int, int] = (20, 40),
    saturation_min: int = 100,
    min_line_length_px: int = 30,
    min_component_pixels: int = 10,
) -> list[LinePixel]:
    """Detect lane markings from an RGB image using HSV thresholds (pure NumPy).

    Algorithm:
      1. Convert RGB → HSV.
      2. Build a white-pixel mask: V > ``white_threshold/255`` and S < 0.3.
      3. Build a yellow-pixel mask: H ∈ ``yellow_hue_range`` and S > ``saturation_min/255``.
      4. Run 4-connected component labelling on each mask.
      5. Filter components by elongation: keep those whose major-axis length
         (estimated as max(row_span, col_span)) ≥ ``min_line_length_px``.
      6. Return a :class:`LinePixel` per surviving component.

    Args:
        rgb: HxWx3 uint8 RGB image.
        white_threshold: Minimum value (V channel, 0-255) for a pixel to be
            considered white.  Lower values detect dimmer markings.
        yellow_hue_range: (lo, hi) hue values (0–360) for yellow detection.
        saturation_min: Minimum saturation (0-255) for yellow detection.
        min_line_length_px: Minimum length of a component's major axis to keep.
        min_component_pixels: Minimum pixel count for a component to be
            considered (filters salt-and-pepper noise).

    Returns:
        List of :class:`LinePixel` objects, one per detected lane segment.
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"rgb must be HxWx3, got shape {rgb.shape}")

    hsv = _rgb_to_hsv(rgb)
    h = hsv[..., 0]
    s = hsv[..., 1]
    v = hsv[..., 2]

    # White mask: high value, low saturation.
    white_v = float(white_threshold) / 255.0
    white_mask = (v >= white_v) & (s < 0.3)

    # Yellow mask: hue in range, sufficient saturation.
    hue_lo, hue_hi = float(yellow_hue_range[0]), float(yellow_hue_range[1])
    sat_min = float(saturation_min) / 255.0
    yellow_mask = (h >= hue_lo) & (h <= hue_hi) & (s >= sat_min)

    results: list[LinePixel] = []
    for colour_kind, mask in [("white", white_mask), ("yellow", yellow_mask)]:
        components = _fast_connected_components(mask, min_component_pixels)
        for pixels in components:
            rows = pixels[:, 0]
            cols = pixels[:, 1]
            row_min, row_max = int(rows.min()), int(rows.max())
            col_min, col_max = int(cols.min()), int(cols.max())
            row_span = row_max - row_min
            col_span = col_max - col_min
            major_axis = max(row_span, col_span)
            if major_axis < min_line_length_px:
                continue
            length_px = float(math.sqrt(row_span**2 + col_span**2))
            results.append(
                LinePixel(
                    pixels=pixels,
                    kind=colour_kind,
                    bbox=(row_min, col_min, row_max, col_max),
                    length_px=length_px,
                )
            )
    return results


def project_camera_lanes_to_graph_edges(
    image_lanes: list[LinePixel],
    calibration: "CameraCalibration",
    graph: "Graph",
    pose_xy_m: tuple[float, float],
    heading_rad: float,
    *,
    max_edge_distance_m: float = 3.5,
    ground_z_m: float = 0.0,
) -> list[LaneMarkingCandidate]:
    """Project pixel-space lane detections onto the ground plane and snap to graph edges.

    For each :class:`LinePixel`, this function:
      1. Picks the midpoint pixel of the component.
      2. Calls :func:`roadgraph_builder.io.camera.projection.pixel_to_ground` to
         get the world ``(x, y)`` of the midpoint.
      3. Finds the nearest edge in ``graph`` by scanning all edge polylines with
         the lateral-distance snap from the existing ``snap_trajectory_to_graph``
         infrastructure.
      4. Assigns a side (left/right) based on the cross-product of the edge
         tangent and the lateral offset vector.
      5. Returns a :class:`LaneMarkingCandidate` per successful projection.

    Components whose midpoint ray points above the horizon or is farther than
    ``max_edge_distance_m`` from any edge are silently dropped.

    Args:
        image_lanes: Output of :func:`detect_lanes_from_image_rgb`.
        calibration: Camera calibration (intrinsic + mount).
        graph: Road graph in the same world meter frame.
        pose_xy_m: Vehicle position (x, y) in the world meter frame.
        heading_rad: Vehicle heading in radians (yaw, CCW from +x).
        max_edge_distance_m: Maximum lateral distance from the projected point
            to the nearest edge centerline (meters).
        ground_z_m: Ground plane height (meters).

    Returns:
        List of :class:`LaneMarkingCandidate` objects.
    """
    from roadgraph_builder.io.camera.calibration import RigidTransform
    from roadgraph_builder.io.camera.projection import pixel_to_ground
    from roadgraph_builder.hd.lidar_fusion import closest_point_on_polyline

    cos_h = math.cos(heading_rad)
    sin_h = math.sin(heading_rad)
    R = np.array([[cos_h, -sin_h, 0.0],
                  [sin_h,  cos_h, 0.0],
                  [0.0,    0.0,   1.0]])
    t = np.array([pose_xy_m[0], pose_xy_m[1], 0.0])
    vehicle_pose = RigidTransform(rotation=R, translation=t)

    candidates: list[LaneMarkingCandidate] = []
    for lane in image_lanes:
        # Use the component midpoint.
        rows = lane.pixels[:, 0]
        cols = lane.pixels[:, 1]
        mid_row = float(np.median(rows))
        mid_col = float(np.median(cols))

        proj = pixel_to_ground(
            float(mid_col),
            float(mid_row),
            calibration,
            vehicle_pose,
            ground_z_m=ground_z_m,
        )
        if proj is None:
            continue  # ray above horizon

        wx, wy = proj

        # Find nearest edge.
        best_edge_id: str | None = None
        best_dist = float("inf")
        best_side = "unknown"
        for e in graph.edges:
            pl = e.polyline
            if len(pl) < 2:
                continue
            d, arc, closest, tan = closest_point_on_polyline(wx, wy, pl)
            if d < best_dist:
                best_dist = d
                best_edge_id = e.id
                # Determine side via cross-product.
                vx = wx - closest[0]
                vy = wy - closest[1]
                cross = tan[0] * vy - tan[1] * vx
                best_side = "left" if cross > 0 else "right"

        if best_dist > max_edge_distance_m:
            continue

        # Confidence: proportional to component length, capped at 1.0.
        confidence = min(1.0, lane.length_px / 200.0)

        candidates.append(
            LaneMarkingCandidate(
                edge_id=best_edge_id,
                world_xy_m=(wx, wy),
                kind=lane.kind,
                side=best_side,
                confidence=confidence,
            )
        )
    return candidates
