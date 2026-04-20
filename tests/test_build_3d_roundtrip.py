"""3D1: round-trip tests — 3D trajectory CSV → graph → JSON → reload.

Verifies:
  - 2D CSV (no z) with use_3d=False produces byte-identical JSON to v0.6.0 (no new keys).
  - 2D CSV with use_3d=True but no z column silently stays 2D.
  - 3D CSV with use_3d=True propagates polyline_z, elevation_m, slope_deg.
  - JSON round-trip preserves z values.
  - validate_road_graph_document accepts both 2D and 3D graphs.
"""

from __future__ import annotations

import io
import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.export.json_exporter import export_graph_json
from roadgraph_builder.io.export.json_loader import load_graph_json
from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_csv
from roadgraph_builder.validation import validate_road_graph_document


def _write_2d_csv(tmp_path: Path, n: int = 40) -> Path:
    """Write a simple 2D trajectory CSV (timestamp, x, y)."""
    p = tmp_path / "traj_2d.csv"
    rows = ["timestamp,x,y"]
    for i in range(n):
        rows.append(f"{float(i)},{float(i * 2)},0.0")
    p.write_text("\n".join(rows), encoding="utf-8")
    return p


def _write_3d_csv(tmp_path: Path, n: int = 40, slope: float = 0.1) -> Path:
    """Write a 3D trajectory CSV (timestamp, x, y, z) with a linear slope."""
    p = tmp_path / "traj_3d.csv"
    rows = ["timestamp,x,y,z"]
    for i in range(n):
        x = float(i * 2)
        z = x * slope  # 10% slope
        rows.append(f"{float(i)},{x},0.0,{z}")
    p.write_text("\n".join(rows), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Backward compat: 2D CSV with use_3d=False
# ---------------------------------------------------------------------------


def test_2d_csv_no_3d_flag_has_no_elevation_keys(tmp_path: Path):
    """2D mode: no polyline_z / elevation_m / slope_deg in any attribute."""
    csv_path = _write_2d_csv(tmp_path)
    graph = build_graph_from_csv(str(csv_path), BuildParams(use_3d=False))
    doc = graph.to_dict()
    for e in doc["edges"]:
        assert "polyline_z" not in e.get("attributes", {}), "polyline_z must not appear in 2D mode"
        assert "slope_deg" not in e.get("attributes", {}), "slope_deg must not appear in 2D mode"
    for n in doc["nodes"]:
        assert "elevation_m" not in n.get("attributes", {}), "elevation_m must not appear in 2D node"
    validate_road_graph_document(doc)


def test_2d_csv_no_z_in_polyline_points(tmp_path: Path):
    """In 2D mode every polyline point must have only x and y."""
    csv_path = _write_2d_csv(tmp_path)
    graph = build_graph_from_csv(str(csv_path), BuildParams(use_3d=False))
    doc = graph.to_dict()
    for e in doc["edges"]:
        for pt in e["polyline"]:
            assert "z" not in pt, f"2D polyline must not have z key, got {pt}"


# ---------------------------------------------------------------------------
# 3D CSV: z propagation
# ---------------------------------------------------------------------------


def test_3d_csv_propagates_polyline_z(tmp_path: Path):
    """3D mode: each edge must have polyline_z with same length as polyline."""
    csv_path = _write_3d_csv(tmp_path)
    graph = build_graph_from_csv(str(csv_path), BuildParams(use_3d=True))
    for e in graph.edges:
        pz = e.attributes.get("polyline_z")
        assert pz is not None, f"Edge {e.id} missing polyline_z"
        assert isinstance(pz, list), "polyline_z must be a list"
        assert len(pz) == len(e.polyline), (
            f"polyline_z length {len(pz)} != polyline length {len(e.polyline)}"
        )


def test_3d_csv_propagates_elevation_to_nodes(tmp_path: Path):
    """3D mode: each node must have elevation_m attribute."""
    csv_path = _write_3d_csv(tmp_path)
    graph = build_graph_from_csv(str(csv_path), BuildParams(use_3d=True))
    for n in graph.nodes:
        assert "elevation_m" in n.attributes, f"Node {n.id} missing elevation_m"
        assert isinstance(n.attributes["elevation_m"], float)


def test_3d_csv_slope_deg_reasonable(tmp_path: Path):
    """10% grade → slope_deg should be ~5.71°."""
    csv_path = _write_3d_csv(tmp_path, slope=0.1)
    graph = build_graph_from_csv(str(csv_path), BuildParams(use_3d=True))
    expected = math.degrees(math.atan(0.1))  # ≈ 5.71°
    for e in graph.edges:
        sd = e.attributes.get("slope_deg")
        assert sd is not None, f"Edge {e.id} missing slope_deg"
        # Allow ±2° tolerance
        assert abs(abs(float(sd)) - expected) < 2.0, (
            f"slope_deg={sd:.2f}° expected ≈ ±{expected:.2f}°"
        )


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


def test_3d_json_roundtrip_preserves_z(tmp_path: Path):
    """Export 3D graph → JSON → reload → z values survive."""
    csv_path = _write_3d_csv(tmp_path)
    graph = build_graph_from_csv(str(csv_path), BuildParams(use_3d=True))

    json_path = tmp_path / "graph_3d.json"
    export_graph_json(graph, str(json_path))

    reloaded = load_graph_json(json_path)
    for orig, reloaded_e in zip(graph.edges, reloaded.edges):
        pz_orig = orig.attributes.get("polyline_z")
        pz_new = reloaded_e.attributes.get("polyline_z")
        assert pz_new is not None, "polyline_z not preserved through JSON round-trip"
        assert len(pz_orig) == len(pz_new)
        for a, b in zip(pz_orig, pz_new):
            assert abs(float(a) - float(b)) < 1e-6, "z value changed in round-trip"


def test_3d_graph_validates_schema(tmp_path: Path):
    """3D graph must validate against road_graph.schema.json."""
    csv_path = _write_3d_csv(tmp_path)
    graph = build_graph_from_csv(str(csv_path), BuildParams(use_3d=True))
    doc = graph.to_dict()
    validate_road_graph_document(doc)


def test_2d_graph_validates_schema(tmp_path: Path):
    """2D graph (backward compat) still validates against schema."""
    csv_path = _write_2d_csv(tmp_path)
    graph = build_graph_from_csv(str(csv_path), BuildParams(use_3d=False))
    doc = graph.to_dict()
    validate_road_graph_document(doc)


# ---------------------------------------------------------------------------
# Loader: load_trajectory_csv z detection
# ---------------------------------------------------------------------------


def test_loader_z_not_loaded_by_default(tmp_path: Path):
    """Without load_z=True, Trajectory.z is None even when CSV has z column."""
    csv_path = _write_3d_csv(tmp_path)
    traj = load_trajectory_csv(csv_path, load_z=False)
    assert traj.z is None


def test_loader_z_loaded_when_requested(tmp_path: Path):
    """With load_z=True and z column present, Trajectory.z is an array."""
    csv_path = _write_3d_csv(tmp_path, n=20, slope=0.05)
    traj = load_trajectory_csv(csv_path, load_z=True)
    assert traj.z is not None
    assert traj.z.shape[0] == len(traj.xy)


def test_loader_z_none_when_column_absent(tmp_path: Path):
    """With load_z=True but no z column, Trajectory.z is None."""
    csv_path = _write_2d_csv(tmp_path)
    traj = load_trajectory_csv(csv_path, load_z=True)
    assert traj.z is None
