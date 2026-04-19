"""Validate ``lane_markings.json`` against the bundled schema."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator


def _load_schema() -> dict[str, Any]:
    pkg = resources.files("roadgraph_builder.schemas")
    raw = (pkg / "lane_markings.schema.json").read_text(encoding="utf-8")
    return json.loads(raw)


def validate_lane_markings_document(data: dict[str, Any]) -> None:
    """Raise ``jsonschema.ValidationError`` if data does not match ``lane_markings.schema.json``."""
    schema = _load_schema()
    Draft202012Validator(schema).validate(data)
