from __future__ import annotations

import pytest

from roadgraph_builder.io.camera.loader import load_camera_observations_placeholder
from roadgraph_builder.io.export.lanelet2 import export_lanelet2
from roadgraph_builder.io.lidar.loader import load_lidar_placeholder


def test_lidar_stub():
    with pytest.raises(NotImplementedError):
        load_lidar_placeholder("x.las")


def test_camera_stub():
    with pytest.raises(NotImplementedError):
        load_camera_observations_placeholder("imgs/")


def test_lanelet2_stub():
    from roadgraph_builder.core.graph.graph import Graph

    with pytest.raises(NotImplementedError):
        export_lanelet2(Graph(), "out.osm")
