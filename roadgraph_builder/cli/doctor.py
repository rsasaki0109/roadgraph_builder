"""``roadgraph_builder doctor`` — quick self-check of the install + bundled assets."""

from __future__ import annotations

import json
import sys
from importlib import resources
from pathlib import Path

import roadgraph_builder


# Example / demo artefacts that should exist alongside the repo checkout. Absent
# files are reported but not treated as fatal, so `doctor` stays useful when
# run from an install that only ships the package (no examples/ tree).
_EXAMPLE_PATHS = (
    "examples/sample_trajectory.csv",
    "examples/toy_map_origin.json",
    "examples/camera_detections_sample.json",
    "examples/turn_restrictions_sample.json",
    "examples/sample_lidar.las",
    "examples/frozen_bundle/manifest.json",
    "scripts/run_demo_bundle.sh",
    "scripts/build_release_bundle.sh",
)

_SCHEMA_FILES = (
    "road_graph.schema.json",
    "camera_detections.schema.json",
    "sd_nav.schema.json",
    "manifest.schema.json",
    "turn_restrictions.schema.json",
    "lane_markings.schema.json",
    "guidance.schema.json",
)


def _check_schema_loads() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    pkg = resources.files("roadgraph_builder.schemas")
    for name in _SCHEMA_FILES:
        label = f"schema:{name}"
        try:
            raw = (pkg / name).read_text(encoding="utf-8")
            doc = json.loads(raw)
        except FileNotFoundError:
            results.append((label, False, "missing"))
            continue
        except json.JSONDecodeError as e:
            results.append((label, False, f"invalid JSON ({e.msg})"))
            continue
        if not isinstance(doc, dict) or doc.get("$schema", "").startswith("http") is False:
            results.append((label, False, "missing $schema"))
            continue
        results.append((label, True, "ok"))
    return results


def _check_las_header(path: Path) -> tuple[bool, str]:
    try:
        from roadgraph_builder.io.lidar.las import read_las_header
    except ImportError as e:
        return False, f"import failed ({e})"
    try:
        header = read_las_header(path)
    except (OSError, ValueError) as e:
        return False, str(e)
    return True, f"LAS {header.version[0]}.{header.version[1]}, {header.point_count} pts"


def run_doctor() -> int:
    print("roadgraph_builder", roadgraph_builder.__version__)
    print("Python", sys.version.split()[0])

    root = Path.cwd()
    failures = 0

    for rel in _EXAMPLE_PATHS:
        p = root / rel
        if p.is_file():
            print(f"{rel}: ok")
        else:
            print(f"{rel}: missing")

    for label, ok, detail in _check_schema_loads():
        status = "ok" if ok else "FAIL"
        print(f"{label}: {status} ({detail})")
        if not ok:
            failures += 1

    las_path = root / "examples" / "sample_lidar.las"
    if las_path.is_file():
        ok, detail = _check_las_header(las_path)
        print(f"LAS header: {'ok' if ok else 'FAIL'} ({detail})")
        if not ok:
            failures += 1

    print("Tip: make demo   or   ./scripts/run_demo_bundle.sh")
    return 0 if failures == 0 else 1
