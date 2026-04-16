"""Validate camera detections JSON against the bundled schema."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator


def _load_schema() -> dict[str, Any]:
    pkg = resources.files("roadgraph_builder.schemas")
    raw = (pkg / "camera_detections.schema.json").read_text(encoding="utf-8")
    return json.loads(raw)


def validate_camera_detections_document(data: dict[str, Any]) -> None:
    """Raise ``jsonschema.ValidationError`` if the document is invalid."""
    schema = _load_schema()
    Draft202012Validator(schema).validate(data)
