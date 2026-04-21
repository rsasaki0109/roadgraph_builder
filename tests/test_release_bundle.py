from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from roadgraph_builder.validation import (
    validate_manifest_document,
    validate_road_graph_document,
    validate_sd_nav_document,
)

ROOT = Path(__file__).resolve().parent.parent
FROZEN = ROOT / "examples" / "frozen_bundle"
FROZEN_STABLE_GENERATED_FILES = [
    "README.txt",
    "nav/sd_nav.json",
    "sim/road_graph.json",
    "sim/map.geojson",
    "sim/trajectory.csv",
    "sim/README.txt",
    "lanelet/map.osm",
]


def test_frozen_bundle_manifest_validates():
    manifest = json.loads((FROZEN / "manifest.json").read_text(encoding="utf-8"))
    validate_manifest_document(manifest)
    assert manifest["dataset_name"] == "roadgraph_sample_bundle"
    assert manifest["turn_restrictions_count"] >= 1


def test_frozen_bundle_nav_sd_nav_validates():
    nav = json.loads((FROZEN / "nav" / "sd_nav.json").read_text(encoding="utf-8"))
    validate_sd_nav_document(nav)
    assert nav["role"] == "navigation_sd_seed"


def test_frozen_bundle_road_graph_validates():
    rg = json.loads((FROZEN / "sim" / "road_graph.json").read_text(encoding="utf-8"))
    validate_road_graph_document(rg)


def test_frozen_bundle_expected_files_present():
    expected = [
        "README.md",
        "README.txt",
        "manifest.json",
        "nav/sd_nav.json",
        "sim/road_graph.json",
        "sim/map.geojson",
        "sim/trajectory.csv",
        "sim/README.txt",
        "lanelet/map.osm",
    ]
    for rel in expected:
        assert (FROZEN / rel).is_file(), f"missing frozen bundle file: {rel}"


def test_default_export_bundle_stable_files_match_frozen_bytes(tmp_path: Path):
    """Default float64 export-bundle path keeps stable artefacts byte-identical."""
    from roadgraph_builder.cli.main import main

    out = tmp_path / "bundle"
    rc = main(
        [
            "export-bundle",
            str(ROOT / "examples" / "sample_trajectory.csv"),
            str(out),
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
            "--fuse-max-dist-m",
            "5.0",
            "--fuse-bins",
            "16",
            "--dataset-name",
            "roadgraph_sample_bundle",
        ]
    )

    assert rc == 0
    for rel in FROZEN_STABLE_GENERATED_FILES:
        frozen_bytes = (FROZEN / rel).read_bytes()
        generated_bytes = (out / rel).read_bytes()
        assert generated_bytes == frozen_bytes, f"stable generated file drifted: {rel}"


@pytest.mark.skipif(
    os.environ.get("ROADGRAPH_RUN_RELEASE_TEST") != "1",
    reason="release bundle shell-out is opt-in (set ROADGRAPH_RUN_RELEASE_TEST=1)",
)
def test_build_release_bundle_script(tmp_path: Path):
    script = ROOT / "scripts" / "build_release_bundle.sh"
    assert script.is_file()

    # Run in a staged repo copy so we don't clobber the checked-in dist/.
    work = tmp_path / "repo"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "dist", ".venv"))

    rb = Path(sys.executable).parent / "roadgraph_builder"
    assert rb.is_file(), f"roadgraph_builder CLI not found next to {sys.executable}"
    result = subprocess.run(
        ["bash", "scripts/build_release_bundle.sh"],
        cwd=work,
        env={**os.environ, "RB": str(rb)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout

    dist = work / "dist"
    tar = dist / "roadgraph_sample_bundle.tar.gz"
    sha = dist / "roadgraph_sample_bundle.sha256"
    out = dist / "roadgraph_sample_bundle"
    assert tar.is_file()
    assert sha.is_file()
    assert (out / "manifest.json").is_file()
    assert (out / "nav" / "sd_nav.json").is_file()
