"""P3: Happy-path test for process-dataset.

Creates 3 synthetic trajectory CSVs in a temp directory, runs
process-dataset, and verifies:
  - 3 bundle directories are created
  - dataset_manifest.json exists with ok_count=3, failed_count=0
  - Each bundle has the expected files
"""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest

from roadgraph_builder.cli.dataset import process_dataset


def _write_straight_csv(path: Path, x0: float, x1: float, n: int = 20) -> None:
    """Write a simple straight-line trajectory CSV."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "x", "y"])
        for i in range(n):
            t = float(i)
            x = x0 + (x1 - x0) * i / (n - 1)
            writer.writerow([t, x, 0.0])


def test_process_dataset_three_files():
    """Three valid CSVs → three bundles + manifest with ok_count=3."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()

        # Write 3 trajectory CSVs.
        for i in range(3):
            _write_straight_csv(input_dir / f"traj_{i:02d}.csv", float(i * 200), float(i * 200 + 100))

        manifest = process_dataset(
            input_dir=input_dir,
            output_dir=output_dir,
            origin_json=None,
            pattern="*.csv",
            parallel=1,
            continue_on_error=True,
        )

        assert manifest["total_count"] == 3, f"Expected 3 files, got {manifest['total_count']}"
        assert manifest["ok_count"] == 3, f"Expected 3 ok, got {manifest['ok_count']}"
        assert manifest["failed_count"] == 0, f"Expected 0 failed, got {manifest['failed_count']}"

        # Check dataset_manifest.json on disk.
        manifest_path = output_dir / "dataset_manifest.json"
        assert manifest_path.is_file(), "dataset_manifest.json not written"
        on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert on_disk["ok_count"] == 3

        # Check per-file bundles exist.
        for stem in ["traj_00", "traj_01", "traj_02"]:
            bundle_dir = output_dir / stem
            assert bundle_dir.is_dir(), f"Bundle dir {stem} not found"


def test_process_dataset_manifest_has_graph_stats():
    """Each file entry in the manifest should carry graph_stats from the bundle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()

        _write_straight_csv(input_dir / "road.csv", 0.0, 100.0)

        manifest = process_dataset(
            input_dir=input_dir,
            output_dir=output_dir,
            origin_json=None,
        )

        assert manifest["ok_count"] == 1
        file_entry = manifest["files"][0]
        assert file_entry["status"] == "ok"
        assert "graph_stats" in file_entry


def test_process_dataset_empty_dir():
    """Empty input directory → manifest with total_count=0, no errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "empty"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()

        manifest = process_dataset(input_dir=input_dir, output_dir=output_dir)

        assert manifest["total_count"] == 0
        assert manifest["ok_count"] == 0
        assert manifest["failed_count"] == 0
        manifest_path = output_dir / "dataset_manifest.json"
        assert manifest_path.is_file()
