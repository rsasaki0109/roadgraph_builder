from __future__ import annotations

import argparse
import errno
import io
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError

from roadgraph_builder.cli.build import _build_params_from_args, run_build, run_visualize
from roadgraph_builder.cli.validate import (
    CliValidationError,
    require_json_object,
    run_validate_document,
    validator_for_command,
)


def _build_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "max_step_m": 25.0,
        "merge_endpoint_m": 8.0,
        "centerline_bins": 32,
        "simplify_tolerance": None,
        "use_3d": False,
        "trajectory_dtype": "float64",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _params(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "use_3d": False,
        "trajectory_xy_dtype": "float64",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_build_params_from_args_maps_cli_options():
    params = _build_params_from_args(
        _build_args(
            max_step_m=40.0,
            merge_endpoint_m=12.0,
            centerline_bins=16,
            simplify_tolerance=0.5,
            use_3d=True,
            trajectory_dtype="float32",
        )
    )

    assert params.max_step_m == 40.0
    assert params.merge_endpoint_m == 12.0
    assert params.centerline_bins == 16
    assert params.simplify_tolerance_m == 0.5
    assert params.use_3d is True
    assert params.trajectory_xy_dtype == "float32"


def test_run_build_uses_multi_csv_loader_and_exporter():
    calls: list[tuple[object, ...]] = []
    params = _params(use_3d=True, trajectory_xy_dtype="float32")

    def unexpected_csv_build(*args: object, **kwargs: object) -> object:
        raise AssertionError("single-CSV builder should not be called")

    rc = run_build(
        argparse.Namespace(input_csv="a.csv", output_json="out.json", extra_csv=["b.csv"]),
        build_params_from_args=lambda args: params,  # type: ignore[return-value]
        load_multi_trajectory_csvs_func=lambda paths, load_z, xy_dtype: calls.append(
            ("load_multi", paths, load_z, xy_dtype)
        )
        or "traj",
        build_graph_from_trajectory_func=lambda traj, build_params: calls.append(
            ("build_traj", traj, build_params)
        )
        or "graph",
        build_graph_from_csv_func=unexpected_csv_build,  # type: ignore[arg-type]
        export_graph_json_func=lambda graph, path: calls.append(("export", graph, path)),
    )

    assert rc == 0
    assert calls == [
        ("load_multi", ["a.csv", "b.csv"], True, "float32"),
        ("build_traj", "traj", params),
        ("export", "graph", "out.json"),
    ]


def test_run_build_reports_missing_input():
    stderr = io.StringIO()

    def missing_csv(path: str, params: object) -> object:
        raise FileNotFoundError(errno.ENOENT, "No such file", path)

    rc = run_build(
        argparse.Namespace(input_csv="missing.csv", output_json="out.json", extra_csv=[]),
        build_params_from_args=lambda args: _params(),  # type: ignore[return-value]
        build_graph_from_csv_func=missing_csv,  # type: ignore[arg-type]
        export_graph_json_func=lambda graph, path: None,
        stderr=stderr,
    )

    assert rc == 1
    assert "File not found: missing.csv" in stderr.getvalue()


def test_run_visualize_injects_loader_builder_and_writer():
    calls: list[tuple[object, ...]] = []
    params = _params(trajectory_xy_dtype="float32")

    rc = run_visualize(
        argparse.Namespace(input_csv="in.csv", output_svg="out.svg", width=100.0, height=50.0),
        build_params_from_args=lambda args: params,  # type: ignore[return-value]
        load_trajectory_csv_func=lambda path, xy_dtype: calls.append(("load", path, xy_dtype)) or "traj",
        build_graph_from_trajectory_func=lambda traj, build_params: calls.append(
            ("build", traj, build_params)
        )
        or "graph",
        write_trajectory_graph_svg_func=lambda traj, graph, path, **kwargs: calls.append(
            ("write_svg", traj, graph, path, kwargs)
        ),
    )

    assert rc == 0
    assert calls == [
        ("load", "in.csv", "float32"),
        ("build", "traj", params),
        ("write_svg", "traj", "graph", "out.svg", {"width": 100.0, "height": 50.0}),
    ]


def test_require_json_object_rejects_non_object_root():
    assert require_json_object({"ok": True}) == {"ok": True}
    with pytest.raises(CliValidationError, match="JSON root"):
        require_json_object([])


def test_run_validate_document_injects_loader_and_validator():
    seen: list[dict[str, object]] = []

    rc = run_validate_document(
        argparse.Namespace(command="validate", input_json="graph.json"),
        load_json=lambda path: {"nodes": [], "edges": []},
        validate_func=lambda doc: seen.append(doc),
    )

    assert rc == 0
    assert seen == [{"nodes": [], "edges": []}]


def test_run_validate_document_reports_bad_root_and_schema_error():
    stderr = io.StringIO()

    rc = run_validate_document(
        argparse.Namespace(command="validate", input_json="bad.json"),
        load_json=lambda path: [],
        validate_func=lambda doc: None,
        stderr=stderr,
    )

    assert rc == 1
    assert "JSON root must be an object" in stderr.getvalue()

    errors: list[str] = []
    rc = run_validate_document(
        argparse.Namespace(command="validate", input_json="bad.json"),
        load_json=lambda path: {"bad": True},
        validate_func=lambda doc: (_ for _ in ()).throw(ValidationError("bad schema")),
        validation_error_func=lambda path, err: errors.append(f"{path}: {err.message}"),
    )

    assert rc == 1
    assert errors == ["bad.json: bad schema"]


def test_validator_for_command_rejects_unknown_command():
    with pytest.raises(CliValidationError, match="Unsupported"):
        validator_for_command("validate-unknown")
