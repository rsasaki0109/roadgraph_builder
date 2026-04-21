from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from roadgraph_builder.cli.export import (
    CliExportError,
    add_export_bundle_parser,
    optional_json_object,
    resolve_bundle_origin,
    resolve_graph_origin,
    run_export_lanelet2,
    run_validate_lanelet2,
    run_validate_lanelet2_tags,
)
from roadgraph_builder.core.graph.graph import Graph


def _graph_with_origin() -> Graph:
    return Graph(metadata={"map_origin": {"lat0": 35.0, "lon0": 139.0}})


def _lanelet_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "input_json": "graph.json",
        "output_osm": "map.osm",
        "origin_lat": None,
        "origin_lon": None,
        "per_lane": False,
        "speed_limit_tagging": "lanelet-attr",
        "lane_markings_json": None,
        "camera_detections_json": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_resolve_graph_origin_uses_explicit_pair_or_metadata():
    graph = _graph_with_origin()

    assert resolve_graph_origin(
        graph,
        origin_lat=1.0,
        origin_lon=2.0,
        command="export-lanelet2",
    ) == (1.0, 2.0)
    assert resolve_graph_origin(
        graph,
        origin_lat=None,
        origin_lon=None,
        command="export-lanelet2",
    ) == (35.0, 139.0)


def test_resolve_graph_origin_reports_partial_or_missing_origin():
    with pytest.raises(CliExportError, match="pass both"):
        resolve_graph_origin(
            _graph_with_origin(),
            origin_lat=1.0,
            origin_lon=None,
            command="export-lanelet2",
        )
    with pytest.raises(CliExportError, match="metadata.map_origin"):
        resolve_graph_origin(
            Graph(),
            origin_lat=None,
            origin_lon=None,
            command="export-lanelet2",
        )


def test_resolve_bundle_origin_prefers_json_then_explicit_pair():
    assert resolve_bundle_origin(
        origin_json="origin.json",
        origin_lat=1.0,
        origin_lon=2.0,
        load_origin=lambda path: (35.0, 139.0),
    ) == (35.0, 139.0)
    assert resolve_bundle_origin(
        origin_json=None,
        origin_lat=1.0,
        origin_lon=2.0,
        load_origin=lambda path: (35.0, 139.0),
    ) == (1.0, 2.0)
    with pytest.raises(CliExportError, match="export-bundle"):
        resolve_bundle_origin(
            origin_json=None,
            origin_lat=1.0,
            origin_lon=None,
            load_origin=lambda path: (35.0, 139.0),
        )


def test_optional_json_object_requires_object_root():
    assert optional_json_object(
        path=None,
        load_json=lambda path: {"unused": True},
        command="export-lanelet2",
        option="--lane-markings-json",
    ) is None
    assert optional_json_object(
        path="data.json",
        load_json=lambda path: {"ok": True},
        command="export-lanelet2",
        option="--lane-markings-json",
    ) == {"ok": True}
    with pytest.raises(CliExportError, match="JSON object"):
        optional_json_object(
            path="data.json",
            load_json=lambda path: [],
            command="export-lanelet2",
            option="--lane-markings-json",
        )


def test_export_bundle_parser_accepts_compact_geojson_flag():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    def add_build_params(p: argparse.ArgumentParser) -> None:
        p.add_argument("--dummy-build-param", action="store_true")

    add_export_bundle_parser(sub, add_build_params=add_build_params)

    args = parser.parse_args(
        ["export-bundle", "in.csv", "out", "--origin-lat", "1", "--origin-lon", "2"]
    )
    assert args.compact_geojson is False
    assert args.compact_bundle_json is False

    compact_args = parser.parse_args(
        [
            "export-bundle",
            "in.csv",
            "out",
            "--origin-lat",
            "1",
            "--origin-lon",
            "2",
            "--compact-geojson",
            "--compact-bundle-json",
        ]
    )
    assert compact_args.compact_geojson is True
    assert compact_args.compact_bundle_json is True


def test_run_export_lanelet2_injects_io_and_exporter():
    calls: list[dict[str, object]] = []

    def export_lanelet2_func(graph: Graph, output_osm: str, **kwargs: object) -> None:
        calls.append({"graph": graph, "output_osm": output_osm, **kwargs})

    rc = run_export_lanelet2(
        _lanelet_args(lane_markings_json="lm.json"),
        load_graph=lambda path: _graph_with_origin(),
        load_json=lambda path: {"lane_markings": []},
        export_lanelet2_func=export_lanelet2_func,
    )

    assert rc == 0
    assert calls == [
        {
            "graph": _graph_with_origin(),
            "output_osm": "map.osm",
            "origin_lat": 35.0,
            "origin_lon": 139.0,
            "speed_limit_tagging": "lanelet-attr",
            "lane_markings": {"lane_markings": []},
            "camera_detections": None,
        }
    ]


def test_run_export_lanelet2_routes_per_lane_exporter():
    calls: list[dict[str, object]] = []

    rc = run_export_lanelet2(
        _lanelet_args(per_lane=True),
        load_graph=lambda path: _graph_with_origin(),
        load_json=lambda path: {},
        export_lanelet2_per_lane_func=lambda graph, output_osm, **kwargs: calls.append(
            {"graph": graph, "output_osm": output_osm, **kwargs}
        ),
    )

    assert rc == 0
    assert calls[0]["output_osm"] == "map.osm"
    assert calls[0]["origin_lat"] == 35.0
    assert calls[0]["origin_lon"] == 139.0


def test_run_export_lanelet2_reports_bad_optional_json():
    stderr = io.StringIO()

    rc = run_export_lanelet2(
        _lanelet_args(camera_detections_json="cam.json"),
        load_graph=lambda path: _graph_with_origin(),
        load_json=lambda path: [],
        export_lanelet2_func=lambda *args, **kwargs: None,
        stderr=stderr,
    )

    assert rc == 1
    assert "--camera-detections-json must be a JSON object" in stderr.getvalue()


def test_run_validate_lanelet2_handles_skipped_and_failed(tmp_path: Path):
    osm = tmp_path / "map.osm"
    osm.write_text("<osm/>", encoding="utf-8")
    stdout = io.StringIO()
    stderr = io.StringIO()

    rc = run_validate_lanelet2(
        argparse.Namespace(input_osm=str(osm), timeout=7),
        run_validator=lambda path, timeout_s: {"status": "skipped", "reason": "missing tool"},
        stdout=stdout,
        stderr=stderr,
    )

    assert rc == 0
    assert json.loads(stdout.getvalue())["status"] == "skipped"
    assert "SKIPPED" in stderr.getvalue()

    stdout = io.StringIO()
    stderr = io.StringIO()
    rc = run_validate_lanelet2(
        argparse.Namespace(input_osm=str(osm), timeout=7),
        run_validator=lambda path, timeout_s: {
            "status": "failed",
            "errors": 1,
            "error_lines": ["bad lanelet"],
        },
        stdout=stdout,
        stderr=stderr,
    )

    assert rc == 1
    assert "bad lanelet" in stderr.getvalue()


def test_run_validate_lanelet2_tags_injects_validator(tmp_path: Path):
    osm = tmp_path / "map.osm"
    osm.write_text("<osm/>", encoding="utf-8")
    stdout = io.StringIO()

    rc = run_validate_lanelet2_tags(
        argparse.Namespace(input_osm=str(osm)),
        validate_tags=lambda path: ([], ["minor warning"]),
        stdout=stdout,
    )

    assert rc == 0
    assert json.loads(stdout.getvalue()) == {"result": "ok", "warnings": 1, "errors": 0}
