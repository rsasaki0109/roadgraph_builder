from __future__ import annotations

import numpy as np

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
from roadgraph_builder.io.camera.detections import apply_camera_detections_to_graph
from roadgraph_builder.io.export.geojson import build_map_geojson


def test_build_map_geojson_includes_lane_boundaries():
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n0",
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                attributes={},
            )
        ],
    )
    enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=2.0))
    traj = np.zeros((0, 2), dtype=np.float64)
    fc = build_map_geojson(
        g,
        traj,
        origin_lat=52.5,
        origin_lon=13.4,
        dataset_name="test",
    )
    kinds = [f["properties"]["kind"] for f in fc["features"]]
    assert "lane_boundary_left" in kinds
    assert "lane_boundary_right" in kinds
    assert "centerline" in kinds


def test_build_map_geojson_semantic_summary():
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n0",
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                attributes={},
            )
        ],
    )
    enrich_sd_to_hd(g, SDToHDConfig(lane_width_m=2.0))
    apply_camera_detections_to_graph(
        g,
        [{"edge_id": "e0", "kind": "speed_limit", "value_kmh": 30}],
    )
    traj = np.zeros((0, 2), dtype=np.float64)
    fc = build_map_geojson(g, traj, origin_lat=52.0, origin_lon=13.0, dataset_name="t")
    cl = [f for f in fc["features"] if f["properties"].get("kind") == "centerline"]
    assert len(cl) == 1
    assert "30" in cl[0]["properties"].get("semantic_summary", "")
