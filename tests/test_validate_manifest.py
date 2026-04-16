from __future__ import annotations

import pytest
from jsonschema import ValidationError

from roadgraph_builder.validation import validate_manifest_document


def test_validate_manifest_minimal():
    validate_manifest_document(
        {
            "manifest_version": 1,
            "generator": "roadgraph_builder",
            "roadgraph_builder_version": "0.2.0",
            "generated_at_utc": "2026-01-01T12:00:00Z",
            "dataset_name": "t",
            "origin_wgs84_deg": {"lat": 52.0, "lon": 13.0},
            "origin_source": "cli",
            "input_trajectory_csv": "x.csv",
            "lane_width_m": 3.5,
            "outputs": {
                "nav_sd_nav": "nav/sd_nav.json",
                "sim_road_graph": "sim/road_graph.json",
                "sim_map_geojson": "sim/map.geojson",
                "sim_trajectory_csv": "sim/trajectory.csv",
                "lanelet_osm": "lanelet/map.osm",
            },
        }
    )


def test_validate_manifest_rejects_bad_generator():
    with pytest.raises(ValidationError):
        validate_manifest_document(
            {
                "manifest_version": 1,
                "generator": "other",
                "roadgraph_builder_version": "0.2.0",
                "generated_at_utc": "2026-01-01T12:00:00Z",
                "dataset_name": "t",
                "origin_wgs84_deg": {"lat": 52.0, "lon": 13.0},
                "origin_source": "cli",
                "input_trajectory_csv": "x.csv",
                "lane_width_m": None,
                "outputs": {
                    "nav_sd_nav": "a",
                    "sim_road_graph": "b",
                    "sim_map_geojson": "c",
                    "sim_trajectory_csv": "d",
                    "lanelet_osm": "e",
                },
            }
        )
