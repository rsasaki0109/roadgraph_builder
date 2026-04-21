"""End-to-end CLI regression test — shells the CLI entry point.

Guards argument parsing, stderr messages, exit codes, file writes, and
inter-step JSON compatibility. Runs against ``examples/sample_trajectory.csv``
so it works in a fresh checkout without external inputs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _rb_command() -> list[str]:
    exe = Path(sys.executable).parent / "roadgraph_builder"
    if exe.is_file():
        return [str(exe)]
    return [
        sys.executable,
        "-c",
        "import sys; from roadgraph_builder.cli.main import main; raise SystemExit(main(sys.argv[1:]))",
    ]


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [*_rb_command(), *args],
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


def test_cli_build_float32_opt_in(tmp_path: Path):
    graph_json = tmp_path / "graph_float32.json"
    r = _run(
        "build",
        str(ROOT / "examples" / "sample_trajectory.csv"),
        str(graph_json),
        "--trajectory-dtype",
        "float32",
    )

    assert r.returncode == 0, r.stderr
    assert graph_json.is_file()
    doc = json.loads(graph_json.read_text(encoding="utf-8"))
    assert len(doc["edges"]) >= 1


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

    # Route along the first edge present in the bundle graph, then turn that
    # route GeoJSON into guidance exactly like the README recipe.
    rg = json.loads((out_dir / "sim" / "road_graph.json").read_text(encoding="utf-8"))
    if rg["edges"]:
        first_edge = rg["edges"][0]
        from_node = first_edge["start_node_id"]
        to_node = first_edge["end_node_id"]
        route_out = tmp_path / "route.geojson"
        r_route = _run(
            "route",
            str(out_dir / "sim" / "road_graph.json"),
            from_node,
            to_node,
            "--output",
            str(route_out),
        )
        assert r_route.returncode == 0, r_route.stderr
        assert route_out.is_file()
        doc = json.loads(r_route.stdout)
        assert doc["from_node"] == from_node
        assert doc["to_node"] == to_node
        assert doc["total_length_m"] >= 0.0

        guidance_out = tmp_path / "guidance.json"
        r_guidance = _run(
            "guidance",
            str(route_out),
            str(out_dir / "nav" / "sd_nav.json"),
            "--output",
            str(guidance_out),
            "--slight-deg",
            "20",
            "--sharp-deg",
            "120",
            "--u-turn-deg",
            "165",
        )
        assert r_guidance.returncode == 0, r_guidance.stderr
        assert guidance_out.is_file()
        r_validate_guidance = _run("validate-guidance", str(guidance_out))
        assert r_validate_guidance.returncode == 0, r_validate_guidance.stderr


def test_cli_export_bundle_compact_flags_validate(tmp_path: Path):
    pretty_dir = tmp_path / "pretty_bundle"
    compact_dir = tmp_path / "compact_bundle"

    base_args = [
        "export-bundle",
        str(ROOT / "examples" / "sample_trajectory.csv"),
        "--origin-json",
        str(ROOT / "examples" / "toy_map_origin.json"),
        "--lane-width-m",
        "0",
        "--dataset-name",
        "compact_e2e",
    ]
    r_pretty = _run(*base_args[:2], str(pretty_dir), *base_args[2:])
    assert r_pretty.returncode == 0, r_pretty.stderr
    r_compact = _run(
        *base_args[:2],
        str(compact_dir),
        *base_args[2:],
        "--compact-geojson",
        "--compact-bundle-json",
    )
    assert r_compact.returncode == 0, r_compact.stderr

    for sub, rel in (
        ("validate-manifest", "manifest.json"),
        ("validate-sd-nav", "nav/sd_nav.json"),
        ("validate", "sim/road_graph.json"),
    ):
        r_validate = _run(sub, str(compact_dir / rel))
        assert r_validate.returncode == 0, f"{sub}: {r_validate.stderr}"

    for rel in ("nav/sd_nav.json", "sim/road_graph.json", "sim/map.geojson"):
        pretty = pretty_dir / rel
        compact = compact_dir / rel
        assert json.loads(compact.read_text(encoding="utf-8")) == json.loads(pretty.read_text(encoding="utf-8"))
        assert compact.stat().st_size < pretty.stat().st_size

    pretty_manifest = json.loads((pretty_dir / "manifest.json").read_text(encoding="utf-8"))
    compact_manifest = json.loads((compact_dir / "manifest.json").read_text(encoding="utf-8"))
    pretty_manifest["generated_at_utc"] = "<dynamic-generated-at>"
    compact_manifest["generated_at_utc"] = "<dynamic-generated-at>"
    assert compact_manifest == pretty_manifest
    assert (compact_dir / "manifest.json").stat().st_size < (pretty_dir / "manifest.json").stat().st_size


def test_cli_missing_input_exits_1(tmp_path: Path):
    r = _run("build", str(tmp_path / "nope.csv"), str(tmp_path / "out.json"))
    assert r.returncode == 1
    assert "File not found" in r.stderr


def test_cli_doctor_runs_from_repo_root():
    r = _run("doctor")
    assert r.returncode == 0, r.stderr
    assert "roadgraph_builder" in r.stdout
    assert "schema:sd_nav.schema.json: ok" in r.stdout
