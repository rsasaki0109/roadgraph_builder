"""Camera / vision inputs — semantics attach to graph as attributes (future).

TODO: traffic lights, stop lines, signs; calibrate and project to road plane.
"""

from roadgraph_builder.io.camera.loader import load_camera_observations_placeholder

__all__ = ["load_camera_observations_placeholder"]
