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
