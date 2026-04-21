"""Smoke tests for scripts/compare_float32_drift.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "compare_float32_drift.py"


def _import_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("compare_float32_drift", SCRIPT)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "trajectory.csv"
    rows = ["timestamp,x,y"]
    for i in range(12):
        rows.append(f"{float(i)},{float(i * 5.0)},0.0")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return csv_path


def test_compare_float32_drift_builds_and_reports(sample_csv: Path, tmp_path: Path) -> None:
    mod = _import_script()

    report = mod.compare_float32_drift(
        sample_csv,
        tmp_path / "drift",
        origin_lat=48.86,
        origin_lon=2.34,
    )

    assert report["topology_changed"] is False
    assert report["trajectory_csv_byte_identical"] is True
    assert report["max_coordinate_drift_m"] < 0.01
    assert report["graph"]["node_count_float64"] == report["graph"]["node_count_float32"]
    assert report["graph"]["edge_count_float64"] == report["graph"]["edge_count_float32"]
    assert (tmp_path / "drift" / "float64" / "sim" / "road_graph.json").is_file()
    assert (tmp_path / "drift" / "float32" / "lanelet" / "map.osm").is_file()


def test_compare_bundles_is_reusable(sample_csv: Path, tmp_path: Path) -> None:
    mod = _import_script()

    report = mod.compare_float32_drift(sample_csv, tmp_path / "drift")
    rebuilt = mod.compare_bundles(
        tmp_path / "drift" / "float64",
        tmp_path / "drift" / "float32",
    )

    assert rebuilt["topology_changed"] == report["topology_changed"]
    assert rebuilt["max_coordinate_drift_m"] == report["max_coordinate_drift_m"]
    assert rebuilt["geojson"]["feature_count_float64"] == rebuilt["geojson"]["feature_count_float32"]


def test_cli_writes_json_and_markdown(sample_csv: Path, tmp_path: Path) -> None:
    json_path = tmp_path / "report.json"
    md_path = tmp_path / "report.md"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(sample_csv),
            str(tmp_path / "cli"),
            "--origin-lat",
            "48.86",
            "--origin-lon",
            "2.34",
            "--fail-on-topology-change",
            "--max-coordinate-drift-m",
            "0.01",
            "--output-json",
            str(json_path),
            "--output-md",
            str(md_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "Max coordinate drift" in result.stdout
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["topology_changed"] is False
    assert "Float32 Drift Comparison" in md_path.read_text(encoding="utf-8")


def test_existing_output_requires_overwrite(sample_csv: Path, tmp_path: Path) -> None:
    mod = _import_script()
    existing = tmp_path / "existing"
    (existing / "float64").mkdir(parents=True)
    (existing / "float64" / "marker.txt").write_text("keep\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        mod.compare_float32_drift(sample_csv, existing)
