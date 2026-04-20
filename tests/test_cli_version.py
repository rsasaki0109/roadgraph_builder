from __future__ import annotations

import re

import pytest

import roadgraph_builder
from roadgraph_builder.cli.main import _build_parser, main


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

    expected_subcommands = set()
    for action in _build_parser()._actions:
        choices = getattr(action, "choices", None)
        if choices and "build" in choices:
            expected_subcommands = set(choices)
            break

    assert expected_subcommands, "could not discover CLI subcommands"
    for name in expected_subcommands:
        assert name in bash_script, f"bash completion missing: {name}"
        assert name in zsh_script, f"zsh completion missing: {name}"
