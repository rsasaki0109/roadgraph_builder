"""Smoke-test the viewer's turn-restriction-aware JS Dijkstra.

Extracts ``buildRestrictionIndex`` + ``dijkstra`` from ``docs/map.html`` and
runs them against a tiny in-memory adjacency — proving the client-side router
honours ``no_left_turn`` and ``only_right_turn`` restrictions (forcing a
30 m detour on a 20 m baseline). Skips when Node.js isn't on ``PATH``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
JS_TEST = ROOT / "tests" / "js" / "test_viewer_dijkstra.mjs"


def test_viewer_dijkstra_honours_turn_restrictions():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH; viewer JS regression test requires Node.js")
    result = subprocess.run(
        [node, str(JS_TEST)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (
        f"node exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK" in result.stdout, result.stdout
