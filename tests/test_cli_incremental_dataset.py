from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from types import SimpleNamespace

from roadgraph_builder.cli.dataset import run_process_dataset
from roadgraph_builder.cli.incremental import run_update_graph, update_graph_summary


def _update_args(existing_json: Path, new_csv: Path, output: Path) -> argparse.Namespace:
    return argparse.Namespace(
        existing_json=str(existing_json),
        new_csv=str(new_csv),
        output=str(output),
        max_step_m=25.0,
        merge_endpoint_m=8.0,
        absorb_tolerance_m=4.0,
        trajectory_dtype="float32",
    )


def _dataset_args(input_dir: Path, output_dir: Path, **overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "origin_json": None,
        "pattern": "*.csv",
        "parallel": 1,
        "continue_on_error": True,
        "lane_width_m": 3.5,
        "dataset_name": None,
        "trajectory_dtype": "float64",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_update_graph_summary_shape():
    graph = SimpleNamespace(nodes=[object(), object()], edges=[object()])
    assert update_graph_summary("out.json", graph) == {"output": "out.json", "nodes": 2, "edges": 1}


def test_run_update_graph_injects_loaders_updater_and_exporter(tmp_path: Path):
    existing = tmp_path / "graph.json"
    new_csv = tmp_path / "new.csv"
    output = tmp_path / "merged.json"
    existing.write_text("{}", encoding="utf-8")
    new_csv.write_text("timestamp,x,y\n0,0,0\n", encoding="utf-8")
    merged = SimpleNamespace(nodes=[1, 2], edges=[1])
    calls: list[tuple[object, ...]] = []
    stdout = io.StringIO()

    rc = run_update_graph(
        _update_args(existing, new_csv, output),
        load_graph_json_func=lambda path: calls.append(("load_graph", path)) or "graph",
        load_trajectory_csv_func=lambda path, xy_dtype: calls.append(("load_traj", path, xy_dtype)) or "traj",
        update_graph_func=lambda graph, traj, **kwargs: calls.append(("update", graph, traj, kwargs)) or merged,
        export_graph_json_func=lambda graph, path: calls.append(("export", graph, path)),
        stdout=stdout,
    )

    assert rc == 0
    assert calls == [
        ("load_graph", existing),
        ("load_traj", new_csv, "float32"),
        (
            "update",
            "graph",
            "traj",
            {"max_step_m": 25.0, "merge_endpoint_m": 8.0, "absorb_tolerance_m": 4.0},
        ),
        ("export", merged, str(output)),
    ]
    assert json.loads(stdout.getvalue()) == {"output": str(output), "nodes": 2, "edges": 1}


def test_run_update_graph_reports_missing_input(tmp_path: Path):
    stderr = io.StringIO()
    rc = run_update_graph(
        _update_args(tmp_path / "missing.json", tmp_path / "new.csv", tmp_path / "out.json"),
        export_graph_json_func=lambda graph, path: None,
        stderr=stderr,
    )

    assert rc == 1
    assert "File not found" in stderr.getvalue()


def test_run_process_dataset_injects_backend_and_prints_manifest(tmp_path: Path):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    calls: list[dict[str, object]] = []
    stdout = io.StringIO()

    rc = run_process_dataset(
        _dataset_args(input_dir, output_dir, dataset_name="demo", trajectory_dtype="float32"),
        process_dataset_func=lambda **kwargs: calls.append(kwargs)
        or {"total_count": 1, "ok_count": 1, "failed_count": 0, "files": []},
        stdout=stdout,
    )

    assert rc == 0
    assert calls == [
        {
            "input_dir": input_dir,
            "output_dir": output_dir,
            "origin_json": None,
            "pattern": "*.csv",
            "parallel": 1,
            "continue_on_error": True,
            "lane_width_m": 3.5,
            "dataset_name_prefix": "demo",
            "trajectory_xy_dtype": "float32",
        }
    ]
    assert json.loads(stdout.getvalue())["ok_count"] == 1


def test_run_process_dataset_reports_missing_paths(tmp_path: Path):
    stderr = io.StringIO()
    rc = run_process_dataset(
        _dataset_args(tmp_path / "missing", tmp_path / "out"),
        process_dataset_func=lambda **kwargs: {},
        stderr=stderr,
    )

    assert rc == 1
    assert "Input directory not found" in stderr.getvalue()

    input_dir = tmp_path / "in"
    input_dir.mkdir()
    stderr = io.StringIO()
    rc = run_process_dataset(
        _dataset_args(input_dir, tmp_path / "out", origin_json=str(tmp_path / "missing_origin.json")),
        process_dataset_func=lambda **kwargs: {},
        stderr=stderr,
    )

    assert rc == 1
    assert "Origin JSON not found" in stderr.getvalue()


def test_run_process_dataset_returns_failure_when_manifest_has_failures(tmp_path: Path):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()

    rc = run_process_dataset(
        _dataset_args(input_dir, output_dir),
        process_dataset_func=lambda **kwargs: {"total_count": 1, "ok_count": 0, "failed_count": 1, "files": []},
        stdout=io.StringIO(),
    )

    assert rc == 1
