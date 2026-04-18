from __future__ import annotations

import re

import pytest

import roadgraph_builder
from roadgraph_builder.cli.main import main


def test_cli_version_long_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith(f"roadgraph_builder {roadgraph_builder.__version__}")


def test_cli_version_short_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["-V"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert re.fullmatch(r"roadgraph_builder \d+\.\d+\.\d+\n", out)


def test_cli_completions_match_subparsers():
    """Smoke-guard against the hand-written bash completion drifting out of sync."""
    from pathlib import Path

    bash_script = (Path(__file__).resolve().parent.parent / "scripts" / "completions" / "roadgraph_builder.bash").read_text(encoding="utf-8")
    zsh_script = (Path(__file__).resolve().parent.parent / "scripts" / "completions" / "_roadgraph_builder").read_text(encoding="utf-8")

    expected_subcommands = {
        "doctor",
        "build",
        "visualize",
        "validate",
        "validate-detections",
        "validate-sd-nav",
        "validate-manifest",
        "validate-turn-restrictions",
        "enrich",
        "inspect-lidar",
        "nearest-node",
        "route",
        "stats",
        "fuse-lidar",
        "export-lanelet2",
        "apply-camera",
        "export-bundle",
    }
    for name in expected_subcommands:
        assert name in bash_script, f"bash completion missing: {name}"
        assert name in zsh_script, f"zsh completion missing: {name}"
