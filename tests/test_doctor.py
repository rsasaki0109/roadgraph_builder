from __future__ import annotations

from pathlib import Path

import pytest

from roadgraph_builder.cli.doctor import run_doctor


def test_doctor_exits_zero(capsys):
    rc = run_doctor()
    out = capsys.readouterr().out
    assert rc == 0
    # Every bundled schema should be reported as ok.
    for schema_name in (
        "road_graph.schema.json",
        "sd_nav.schema.json",
        "manifest.schema.json",
        "turn_restrictions.schema.json",
        "camera_detections.schema.json",
    ):
        assert f"schema:{schema_name}: ok" in out
    assert "LAS header: ok" in out


def test_doctor_still_exits_zero_with_missing_examples(tmp_path: Path, monkeypatch, capsys):
    # cwd without the examples/ tree: missing files are reported but not fatal.
    monkeypatch.chdir(tmp_path)
    rc = run_doctor()
    out = capsys.readouterr().out
    assert rc == 0
    assert "examples/sample_trajectory.csv: missing" in out
    # Schemas are shipped inside the package, so they must still pass.
    assert "schema:road_graph.schema.json: ok" in out


def test_doctor_reports_failure_on_corrupt_schema(tmp_path: Path, monkeypatch, capsys):
    from importlib import resources

    from roadgraph_builder.cli import doctor as mod

    class _BadFile:
        def read_text(self, encoding: str = "utf-8") -> str:  # noqa: ARG002
            return "{not json"

    class _Pkg:
        def __truediv__(self, name: str):
            return _BadFile()

    monkeypatch.setattr(resources, "files", lambda _pkg: _Pkg())
    monkeypatch.chdir(tmp_path)
    rc = mod.run_doctor()
    out = capsys.readouterr().out
    assert rc == 1
    assert "schema:road_graph.schema.json: FAIL" in out
