from __future__ import annotations

import argparse
import io
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from jsonschema import ValidationError

from roadgraph_builder.cli.guidance import (
    guidance_steps_to_document,
    run_guidance,
    run_validate_guidance,
)
from roadgraph_builder.cli.osm import (
    CliOsmError,
    highway_filter_from_arg,
    resolve_osm_origin,
    turn_restrictions_document,
)


@dataclass
class _GuidanceStep:
    step_index: int
    edge_id: str
    start_distance_m: float
    length_m: float
    maneuver_at_end: str
    heading_change_deg: float
    junction_type_at_end: str
    description: str
    sd_nav_edge_maneuvers: list[str]


def test_highway_filter_from_arg_parses_csv():
    assert highway_filter_from_arg(None) is None
    assert highway_filter_from_arg("primary, secondary,, residential ") == {
        "primary",
        "secondary",
        "residential",
    }


def test_resolve_osm_origin_prefers_json_then_explicit_pair():
    assert resolve_osm_origin(
        origin_json="origin.json",
        origin_lat=1.0,
        origin_lon=2.0,
        load_origin=lambda path: (35.0, 139.0),
        command="build-osm-graph",
    ) == (35.0, 139.0)
    assert resolve_osm_origin(
        origin_json=None,
        origin_lat=1.0,
        origin_lon=2.0,
        load_origin=lambda path: (35.0, 139.0),
        command="build-osm-graph",
    ) == (1.0, 2.0)
    with pytest.raises(CliOsmError, match="build-osm-graph"):
        resolve_osm_origin(
            origin_json=None,
            origin_lat=1.0,
            origin_lon=None,
            load_origin=lambda path: (35.0, 139.0),
            command="build-osm-graph",
        )


def test_turn_restrictions_document_shape():
    restrictions = [{"id": "tr_1"}]

    assert turn_restrictions_document(restrictions) == {
        "format_version": 1,
        "attribution": "© OpenStreetMap contributors",
        "license": "ODbL-1.0",
        "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "turn_restrictions": restrictions,
    }


def test_guidance_steps_to_document_serializes_cli_shape():
    doc = guidance_steps_to_document(
        [
            _GuidanceStep(
                step_index=0,
                edge_id="e1",
                start_distance_m=0.0,
                length_m=12.0,
                maneuver_at_end="right",
                heading_change_deg=90.0,
                junction_type_at_end="t_junction",
                description="Turn right",
                sd_nav_edge_maneuvers=["right"],
            )
        ]
    )

    assert doc == {
        "steps": [
            {
                "step_index": 0,
                "edge_id": "e1",
                "start_distance_m": 0.0,
                "length_m": 12.0,
                "maneuver_at_end": "right",
                "heading_change_deg": 90.0,
                "junction_type_at_end": "t_junction",
                "description": "Turn right",
                "sd_nav_edge_maneuvers": ["right"],
            }
        ]
    }


def test_run_guidance_injects_builder_and_writes_output(tmp_path: Path):
    stderr = io.StringIO()
    out = tmp_path / "guidance.json"

    rc = run_guidance(
        argparse.Namespace(
            route_geojson="route.geojson",
            sd_nav_json="sd_nav.json",
            output=str(out),
            slight_deg=20.0,
            sharp_deg=120.0,
            u_turn_deg=165.0,
        ),
        load_json=lambda path: {"features": []},
        build_guidance_func=lambda route, sd_nav, **kwargs: [
            _GuidanceStep(0, "e1", 0.0, 1.0, "arrive", 0.0, "", "Arrive", [])
        ],
        stderr=stderr,
    )

    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["steps"][0]["edge_id"] == "e1"
    assert "1 steps" in stderr.getvalue()


def test_run_guidance_validates_json_roots():
    stderr = io.StringIO()

    rc = run_guidance(
        argparse.Namespace(
            route_geojson="route.geojson",
            sd_nav_json="sd_nav.json",
            output="guidance.json",
            slight_deg=20.0,
            sharp_deg=120.0,
            u_turn_deg=165.0,
        ),
        load_json=lambda path: [] if path == "route.geojson" else {},
        build_guidance_func=lambda route, sd_nav, **kwargs: [],
        stderr=stderr,
    )

    assert rc == 1
    assert "route GeoJSON root must be an object" in stderr.getvalue()


def test_run_validate_guidance_injects_validator_and_error_reporter():
    errors: list[str] = []
    stderr = io.StringIO()

    rc = run_validate_guidance(
        argparse.Namespace(input_json="guidance.json"),
        load_json=lambda path: {"steps": []},
        validate_guidance_func=lambda doc: None,
        stderr=stderr,
    )

    assert rc == 0

    rc = run_validate_guidance(
        argparse.Namespace(input_json="bad.json"),
        load_json=lambda path: {"bad": True},
        validate_guidance_func=lambda doc: (_ for _ in ()).throw(
            ValidationError("bad guidance")
        ),
        validation_error_func=lambda path, err: errors.append(f"{path}: {err.message}"),
        stderr=stderr,
    )

    assert rc == 1
    assert errors == ["bad.json: bad guidance"]
