"""P3: Partial-failure test for process-dataset.

Creates a mix of valid and invalid CSVs, verifies that:
  - --continue-on-error (default True) lets processing continue
  - The invalid file appears with status=failed in the manifest
  - Valid files still produce bundles
  - The manifest exit-code logic works (failed_count > 0)
"""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest

from roadgraph_builder.cli.dataset import process_dataset


def _write_straight_csv(path: Path, x0: float, x1: float, n: int = 20) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "x", "y"])
        for i in range(n):
            t = float(i)
            x = x0 + (x1 - x0) * i / (n - 1)
            writer.writerow([t, x, 0.0])


def _write_invalid_csv(path: Path) -> None:
    """Write a CSV with a missing required column (no 'y' column)."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "x"])  # Missing 'y'!
        writer.writerow([0.0, 1.0])
        writer.writerow([1.0, 2.0])


def test_partial_failure_continue_on_error():
    """One invalid file → failed_count=1; other files still succeed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()

        # 2 good files + 1 bad
        _write_straight_csv(input_dir / "good_a.csv", 0.0, 100.0)
        _write_invalid_csv(input_dir / "bad_b.csv")
        _write_straight_csv(input_dir / "good_c.csv", 200.0, 300.0)

        manifest = process_dataset(
            input_dir=input_dir,
            output_dir=output_dir,
            origin_json=None,
            continue_on_error=True,
        )

        assert manifest["total_count"] == 3
        assert manifest["ok_count"] == 2, f"Expected 2 ok, got {manifest['ok_count']}"
        assert manifest["failed_count"] == 1, f"Expected 1 failed, got {manifest['failed_count']}"

        # Bad file has status=failed + error message.
        bad_entry = next(
            (f for f in manifest["files"] if "bad_b" in f["file"]),
            None,
        )
        assert bad_entry is not None, "bad_b.csv entry not found in manifest"
        assert bad_entry["status"] == "failed"
        assert "error" in bad_entry and bad_entry["error"]

        # Good files have bundles.
        assert (output_dir / "good_a").is_dir(), "good_a bundle missing"
        assert (output_dir / "good_c").is_dir(), "good_c bundle missing"


def test_partial_failure_manifest_on_disk():
    """dataset_manifest.json reflects partial failure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()

        _write_straight_csv(input_dir / "ok.csv", 0.0, 100.0)
        _write_invalid_csv(input_dir / "fail.csv")

        process_dataset(
            input_dir=input_dir,
            output_dir=output_dir,
            continue_on_error=True,
        )

        manifest_path = output_dir / "dataset_manifest.json"
        assert manifest_path.is_file()
        on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert on_disk["failed_count"] == 1
        assert on_disk["ok_count"] == 1


def test_no_continue_on_error_raises():
    """With continue_on_error=False, the first failure raises RuntimeError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()

        _write_invalid_csv(input_dir / "bad.csv")

        with pytest.raises(RuntimeError, match="process-dataset"):
            process_dataset(
                input_dir=input_dir,
                output_dir=output_dir,
                continue_on_error=False,
            )
