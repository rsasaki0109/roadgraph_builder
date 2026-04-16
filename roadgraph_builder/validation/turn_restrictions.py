"""Validate manual/camera turn-restrictions documents (``turn_restrictions.schema.json``)."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator


def _load_schema() -> dict[str, Any]:
    pkg = resources.files("roadgraph_builder.schemas")
    raw = (pkg / "turn_restrictions.schema.json").read_text(encoding="utf-8")
    return json.loads(raw)


def validate_turn_restrictions_document(data: dict[str, Any]) -> None:
    """Raise ``jsonschema.ValidationError`` if ``data`` does not match the schema."""
    schema = _load_schema()
    Draft202012Validator(schema).validate(data)
