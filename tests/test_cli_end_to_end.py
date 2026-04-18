"""End-to-end CLI regression test — shells the installed entry point.

Guards the CLI surface that unit tests touch via ``main()`` in-process:
argument parsing, stderr messages, exit codes, file writes, and inter-step
JSON compatibility. Runs against ``examples/sample_trajectory.csv`` so it
works in a fresh checkout without external inputs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _rb() -> str:
    exe = Path(sys.executable).parent / "roadgraph_builder"
    if not exe.is_file():
        pytest.skip(f"roadgraph_builder CLI not found next to {sys.executable}")
    return str(exe)


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [_rb(), *args],
        cwd=str(cwd) if cwd else str(ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return result


def test_cli_build_and_validate(tmp_path: Path):
    graph_json = tmp_path / "graph.json"
    r = _run(
        "build",
        str(ROOT / "examples" / "sample_trajectory.csv"),
        str(graph_json),
    )
    assert r.returncode == 0, r.stderr
    assert graph_json.is_file()

    r2 = _run("validate", str(graph_json))
    assert r2.returncode == 0, r2.stderr


def test_cli_export_bundle_full_pipeline_then_stats_route(tmp_path: Path):
    out_dir = tmp_path / "bundle"
    r = _run(
        "export-bundle",
        str(ROOT / "examples" / "sample_trajectory.csv"),
        str(out_dir),
        "--origin-json",
        str(ROOT / "examples" / "toy_map_origin.json"),
        "--lane-width-m",
        "3.5",
        "--detections-json",
        str(ROOT / "examples" / "camera_detections_sample.json"),
        "--turn-restrictions-json",
        str(ROOT / "examples" / "turn_restrictions_sample.json"),
        "--lidar-points",
        str(ROOT / "examples" / "sample_lidar.las"),
        "--fuse-bins",
        "16",
        "--dataset-name",
        "e2e",
    )
    assert r.returncode == 0, r.stderr

    # Every documented output is written.
    for rel in (
        "manifest.json",
        "nav/sd_nav.json",
        "sim/road_graph.json",
        "sim/map.geojson",
        "sim/trajectory.csv",
        "lanelet/map.osm",
        "README.txt",
    ):
        assert (out_dir / rel).is_file(), f"missing: {rel}"

    # manifest shape
    man = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert man["manifest_version"] == 1
    assert man["dataset_name"] == "e2e"
    assert man["turn_restrictions_count"] >= 1
    assert man["lidar_points"]["point_count"] >= 1
    assert man["graph_stats"]["edge_count"] == len(
        json.loads((out_dir / "sim" / "road_graph.json").read_text(encoding="utf-8"))["edges"]
    )

    # Downstream validators accept the bundle.
    for sub in ("validate-manifest", "validate-sd-nav"):
        sub_path = {
            "validate-manifest": out_dir / "manifest.json",
            "validate-sd-nav": out_dir / "nav" / "sd_nav.json",
        }[sub]
        r2 = _run(sub, str(sub_path))
        assert r2.returncode == 0, f"{sub}: {r2.stderr}"
    r3 = _run("validate", str(out_dir / "sim" / "road_graph.json"))
    assert r3.returncode == 0, r3.stderr

    # Stats CLI agrees with the manifest.
    r_stats = _run("stats", str(out_dir / "sim" / "road_graph.json"))
    assert r_stats.returncode == 0, r_stats.stderr
    stats_doc = json.loads(r_stats.stdout)
    assert stats_doc["graph_stats"]["edge_count"] == man["graph_stats"]["edge_count"]
    assert (
        stats_doc["junctions"]["total_nodes"]
        == man["junctions"]["total_nodes"]
    )

    # Route between the first two nodes present in the bundle graph.
    rg = json.loads((out_dir / "sim" / "road_graph.json").read_text(encoding="utf-8"))
    node_ids = [n["id"] for n in rg["nodes"]]
    if len(node_ids) >= 2:
        route_out = tmp_path / "route.geojson"
        r_route = _run(
            "route",
            str(out_dir / "sim" / "road_graph.json"),
            node_ids[0],
            node_ids[1],
            "--output",
            str(route_out),
        )
        # Disjoint components in the toy bundle are fine; either succeed with
        # a geojson or report "no path" cleanly.
        if r_route.returncode == 0:
            assert route_out.is_file()
            doc = json.loads(r_route.stdout)
            assert doc["from_node"] == node_ids[0]
            assert doc["to_node"] == node_ids[1]
            assert doc["total_length_m"] >= 0.0
        else:
            assert "no path" in r_route.stderr or "not in the graph" in r_route.stderr


def test_cli_missing_input_exits_1(tmp_path: Path):
    r = _run("build", str(tmp_path / "nope.csv"), str(tmp_path / "out.json"))
    assert r.returncode == 1
    assert "File not found" in r.stderr


def test_cli_doctor_runs_from_repo_root():
    r = _run("doctor")
    assert r.returncode == 0, r.stderr
    assert "roadgraph_builder" in r.stdout
    assert "schema:sd_nav.schema.json: ok" in r.stdout
