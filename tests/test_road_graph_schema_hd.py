from __future__ import annotations

import pytest
from jsonschema import ValidationError

from roadgraph_builder.validation import validate_road_graph_document


def test_schema_requires_kind_in_semantic_rules():
    doc = {
        "schema_version": 1,
        "nodes": [],
        "edges": [
            {
                "id": "e0",
                "start_node_id": "n0",
                "end_node_id": "n0",
                "polyline": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}],
                "attributes": {"hd": {"semantic_rules": [{"not_kind": 1}]}},
            }
        ],
    }
    with pytest.raises(ValidationError):
        validate_road_graph_document(doc)


def test_schema_accepts_semantic_rules_with_kind():
    validate_road_graph_document(
        {
            "schema_version": 1,
            "nodes": [],
            "edges": [
                {
                    "id": "e0",
                    "start_node_id": "n0",
                    "end_node_id": "n0",
                    "polyline": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}],
                    "attributes": {
                        "hd": {
                            "semantic_rules": [
                                {"kind": "speed_limit", "value_kmh": 40},
                            ]
                        }
                    },
                }
            ],
        }
    )
