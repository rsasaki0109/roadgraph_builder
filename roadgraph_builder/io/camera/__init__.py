"""Camera / vision inputs — semantics attach to graph as attributes.

Two layers:

* ``load_camera_detections_json`` + ``apply_camera_detections_to_graph`` merge
  precomputed edge-keyed labels into ``attributes.hd.semantic_rules``.
* ``CameraCalibration`` + ``project_image_detections_to_graph_edges`` take
  per-image vehicle poses and pixel annotations, project them onto the ground
  plane via a pinhole camera model, and snap to the nearest graph edge —
  producing the same edge-keyed schema from the first layer.
"""

from roadgraph_builder.io.camera.calibration import (
    CameraCalibration,
    CameraIntrinsic,
    RigidTransform,
    load_camera_calibration,
    rpy_to_matrix,
)
from roadgraph_builder.io.camera.detections import apply_camera_detections_to_graph, load_camera_detections_json
from roadgraph_builder.io.camera.loader import load_camera_observations_placeholder
from roadgraph_builder.io.camera.pipeline import (
    CameraProjectionResult,
    project_image_detections_to_graph_edges,
)
from roadgraph_builder.io.camera.projection import (
    GroundProjection,
    load_image_detections_json,
    pixel_to_ground,
    project_image_detections,
)

__all__ = [
    "CameraCalibration",
    "CameraIntrinsic",
    "CameraProjectionResult",
    "GroundProjection",
    "RigidTransform",
    "apply_camera_detections_to_graph",
    "load_camera_calibration",
    "load_camera_detections_json",
    "load_camera_observations_placeholder",
    "load_image_detections_json",
    "pixel_to_ground",
    "project_image_detections",
    "project_image_detections_to_graph_edges",
    "rpy_to_matrix",
]
