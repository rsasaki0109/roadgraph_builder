"""Camera / vision inputs — semantics attach to graph as attributes (future).

``load_camera_detections_json`` + ``apply_camera_detections_to_graph`` merge
precomputed labels into ``attributes.hd.semantic_rules``.

TODO: calibrate and project image detections to road plane (raw images).
"""

from roadgraph_builder.io.camera.detections import apply_camera_detections_to_graph, load_camera_detections_json
from roadgraph_builder.io.camera.loader import load_camera_observations_placeholder

__all__ = [
    "apply_camera_detections_to_graph",
    "load_camera_detections_json",
    "load_camera_observations_placeholder",
]
