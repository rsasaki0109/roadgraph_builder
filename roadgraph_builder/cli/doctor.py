"""Print version / Python info and whether example paths exist (run from repo root)."""

from __future__ import annotations

import sys
from pathlib import Path

import roadgraph_builder


def run_doctor() -> int:
    print("roadgraph_builder", roadgraph_builder.__version__)
    print("Python", sys.version.split()[0])
    root = Path.cwd()
    checks = [
        root / "examples" / "sample_trajectory.csv",
        root / "examples" / "toy_map_origin.json",
        root / "examples" / "camera_detections_sample.json",
        root / "scripts" / "run_demo_bundle.sh",
    ]
    for p in checks:
        try:
            label = str(p.relative_to(root))
        except ValueError:
            label = str(p)
        print(label + ":", "ok" if p.is_file() else "missing")
    print("Tip: make demo   or   ./scripts/run_demo_bundle.sh")
    return 0
