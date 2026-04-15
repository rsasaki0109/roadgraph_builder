from __future__ import annotations

import pytest
from jsonschema import ValidationError

from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_csv
from roadgraph_builder.validation import validate_road_graph_document


def test_build_output_validates_against_schema(sample_csv_path):
    g = build_graph_from_csv(str(sample_csv_path), BuildParams(max_step_m=25.0))
    validate_road_graph_document(g.to_dict())


def test_invalid_document_raises():
    with pytest.raises(ValidationError):
        validate_road_graph_document({"nodes": [], "edges": "bad"})
