from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import ValidationError

from roadgraph_builder.io.export.bundle import build_sd_nav_document
from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
from roadgraph_builder.validation import validate_sd_nav_document

ROOT = Path(__file__).resolve().parent.parent


def test_validate_sd_nav_from_bundle():
    traj = load_trajectory_csv(ROOT / "examples" / "sample_trajectory.csv")
    g = build_graph_from_trajectory(traj, BuildParams())
    doc = build_sd_nav_document(g)
    validate_sd_nav_document(doc)


def test_validate_sd_nav_rejects_wrong_role():
    with pytest.raises(ValidationError):
        validate_sd_nav_document(
            {
                "role": "wrong",
                "schema_version": 1,
                "nodes": [],
                "edges": [],
            }
        )


def test_validate_sd_nav_accepts_turn_restrictions_extension():
    doc = {
        "role": "navigation_sd_seed",
        "schema_version": 1,
        "nodes": [],
        "edges": [],
        "turn_restrictions": [
            {
                "id": "tr_001",
                "junction_node_id": "n12",
                "from_edge_id": "e7",
                "from_direction": "forward",
                "to_edge_id": "e9",
                "to_direction": "reverse",
                "restriction": "no_left_turn",
                "source": "manual",
                "confidence": 1.0,
            }
        ],
    }
    validate_sd_nav_document(doc)


def test_validate_sd_nav_rejects_invalid_turn_restriction():
    doc = {
        "role": "navigation_sd_seed",
        "schema_version": 1,
        "nodes": [],
        "edges": [],
        "turn_restrictions": [
            {
                "id": "tr_001",
                "junction_node_id": "n12",
                "from_edge_id": "e7",
                "from_direction": "sideways",
                "to_edge_id": "e9",
                "to_direction": "forward",
                "restriction": "no_left_turn",
                "source": "manual",
            }
        ],
    }
    with pytest.raises(ValidationError):
        validate_sd_nav_document(doc)

    bad_confidence = deepcopy(doc)
    bad_confidence["turn_restrictions"][0]["from_direction"] = "forward"
    bad_confidence["turn_restrictions"][0]["confidence"] = 1.2
    with pytest.raises(ValidationError):
        validate_sd_nav_document(bad_confidence)
