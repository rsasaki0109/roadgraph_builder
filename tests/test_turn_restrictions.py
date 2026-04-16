from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from roadgraph_builder.io.export.bundle import export_map_bundle
from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
from roadgraph_builder.navigation.turn_restrictions import (
    load_turn_restrictions_json,
    merge_turn_restrictions,
    turn_restrictions_from_camera_detections,
)
from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
from roadgraph_builder.validation import (
    validate_sd_nav_document,
    validate_turn_restrictions_document,
)

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PATH = ROOT / "examples" / "turn_restrictions_sample.json"


def test_load_turn_restrictions_json_roundtrips_sample():
    entries = load_turn_restrictions_json(SAMPLE_PATH)
    assert len(entries) == 2
    ids = [e["id"] for e in entries]
    assert ids == ["tr_toy_001", "tr_toy_002"]
    for e in entries:
        assert e["from_direction"] in ("forward", "reverse")
        assert e["to_direction"] in ("forward", "reverse")
        assert e["source"] == "manual"
    assert entries[1]["confidence"] == 0.9


def test_load_turn_restrictions_json_bare_list(tmp_path: Path):
    doc = [
        {
            "junction_node_id": "n5",
            "from_edge_id": "e10",
            "to_edge_id": "e11",
            "restriction": "no_right_turn",
        }
    ]
    p = tmp_path / "tr.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    out = load_turn_restrictions_json(p)
    assert len(out) == 1
    assert out[0]["id"] == "tr_manual_0000"
    assert out[0]["source"] == "manual"
    assert out[0]["from_direction"] == "forward"
    assert out[0]["to_direction"] == "forward"


def test_load_turn_restrictions_json_rejects_bad_enum(tmp_path: Path):
    doc = [
        {
            "junction_node_id": "n5",
            "from_edge_id": "e10",
            "to_edge_id": "e11",
            "restriction": "not_a_real_restriction",
        }
    ]
    p = tmp_path / "tr.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError):
        load_turn_restrictions_json(p)


def test_turn_restrictions_from_camera_detections_filters_and_defaults():
    observations = [
        {"edge_id": "e0", "kind": "speed_limit", "value_kmh": 50},
        {"edge_id": "e0", "kind": "traffic_light", "confidence": 0.7},
        {
            "edge_id": "e0",
            "kind": "turn_restriction",
            "junction_node_id": "n1",
            "from_edge_id": "e0",
            "to_edge_id": "e1",
            "restriction": "no_left_turn",
        },
        {
            "edge_id": "e1",
            "kind": "turn_restriction",
            "junction_node_id": "n2",
            "from_edge_id": "e1",
            "to_edge_id": "e0",
            "restriction": "no_u_turn",
            "confidence": 0.5,
        },
    ]
    out = turn_restrictions_from_camera_detections(observations)
    assert len(out) == 2
    assert [e["source"] for e in out] == ["camera_detection", "camera_detection"]
    assert [e["id"] for e in out] == ["tr_camera_0000", "tr_camera_0001"]
    assert out[1]["confidence"] == 0.5


def test_turn_restrictions_from_camera_skips_missing_junction():
    obs = [
        {
            "edge_id": "e0",
            "kind": "turn_restriction",
            "from_edge_id": "e0",
            "to_edge_id": "e1",
            "restriction": "no_left_turn",
        },
    ]
    assert turn_restrictions_from_camera_detections(obs) == []


def test_merge_turn_restrictions_dedupes_and_preserves_order():
    manual = [
        {"id": "a", "restriction": "no_left_turn"},
        {"id": "b", "restriction": "no_right_turn"},
    ]
    camera = [
        {"id": "b", "restriction": "only_straight"},  # loses to manual
        {"id": "c", "restriction": "no_u_turn"},
    ]
    merged = merge_turn_restrictions(manual, camera)
    assert [e["id"] for e in merged] == ["a", "b", "c"]
    assert merged[1]["restriction"] == "no_right_turn"


def test_validate_turn_restrictions_document_accepts_sample():
    data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    validate_turn_restrictions_document(data)


def test_validate_turn_restrictions_document_rejects_bad_enum():
    bad = {
        "turn_restrictions": [
            {
                "id": "x",
                "junction_node_id": "n1",
                "from_edge_id": "e0",
                "from_direction": "forward",
                "to_edge_id": "e1",
                "to_direction": "forward",
                "restriction": "not_valid",
                "source": "manual",
            }
        ]
    }
    with pytest.raises(ValidationError):
        validate_turn_restrictions_document(bad)


def test_export_map_bundle_embeds_turn_restrictions(tmp_path: Path):
    csv_path = ROOT / "examples" / "sample_trajectory.csv"
    traj = load_trajectory_csv(csv_path)
    g = build_graph_from_trajectory(traj, BuildParams())
    export_map_bundle(
        g,
        traj.xy,
        csv_path,
        tmp_path,
        origin_lat=52.52,
        origin_lon=13.405,
        dataset_name="tr_test",
        lane_width_m=3.5,
        detections_json=None,
        turn_restrictions_json=SAMPLE_PATH,
    )

    nav = json.loads((tmp_path / "nav" / "sd_nav.json").read_text(encoding="utf-8"))
    assert "turn_restrictions" in nav
    assert len(nav["turn_restrictions"]) == 2
    assert nav["turn_restrictions"][0]["id"] == "tr_toy_001"
    validate_sd_nav_document(nav)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["turn_restrictions_json"] == SAMPLE_PATH.name
    assert manifest["turn_restrictions_count"] == 2
