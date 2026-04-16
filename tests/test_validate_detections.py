from __future__ import annotations

import pytest
from jsonschema import ValidationError

from roadgraph_builder.validation import validate_camera_detections_document


def test_validate_sample_camera_json():
    validate_camera_detections_document(
        {
            "format_version": 1,
            "observations": [{"edge_id": "e0", "kind": "speed_limit", "value_kmh": 50}],
        }
    )


def test_validate_rejects_missing_observations():
    with pytest.raises(ValidationError):
        validate_camera_detections_document({"format_version": 1})
