"""Load, merge, and coerce legal/regulatory turn restrictions for ``sd_nav``.

These entries are kept separate from geometry-derived ``allowed_maneuvers`` on
purpose. A restriction ties a directed edge transition at a junction node to a
restriction enum (e.g. ``no_left_turn``). See ``sd_nav.schema.json`` for the
full per-item shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


ALLOWED_RESTRICTIONS = (
    "no_left_turn",
    "no_right_turn",
    "no_straight",
    "no_u_turn",
    "only_left",
    "only_right",
    "only_straight",
)
ALLOWED_DIRECTIONS = ("forward", "reverse")
REQUIRED_FIELDS = ("junction_node_id", "from_edge_id", "to_edge_id", "restriction")


def _coerce_item(raw: Any, *, index: int, default_source: str, id_prefix: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TypeError(f"turn_restrictions[{index}] must be an object, got {type(raw).__name__}")

    out: dict[str, Any] = {}

    for field in REQUIRED_FIELDS:
        value = raw.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"turn_restrictions[{index}] missing required string field '{field}'"
            )
        out[field] = value

    if out["restriction"] not in ALLOWED_RESTRICTIONS:
        raise ValueError(
            f"turn_restrictions[{index}] restriction '{out['restriction']}' not in "
            f"{ALLOWED_RESTRICTIONS}"
        )

    for key in ("from_direction", "to_direction"):
        value = raw.get(key, "forward")
        if not isinstance(value, str) or value not in ALLOWED_DIRECTIONS:
            raise ValueError(
                f"turn_restrictions[{index}] {key}='{value}' must be one of {ALLOWED_DIRECTIONS}"
            )
        out[key] = value

    source = raw.get("source", default_source)
    if not isinstance(source, str) or not source:
        raise ValueError(f"turn_restrictions[{index}] source must be a non-empty string")
    out["source"] = source

    entry_id = raw.get("id")
    if entry_id is None:
        out["id"] = f"{id_prefix}{index:04d}"
    elif not isinstance(entry_id, str) or not entry_id:
        raise ValueError(f"turn_restrictions[{index}] id must be a non-empty string when present")
    else:
        out["id"] = entry_id

    if "confidence" in raw:
        conf = raw["confidence"]
        if not isinstance(conf, (int, float)) or isinstance(conf, bool):
            raise TypeError(f"turn_restrictions[{index}] confidence must be a number")
        conf = float(conf)
        if not 0.0 <= conf <= 1.0:
            raise ValueError(f"turn_restrictions[{index}] confidence {conf} outside [0, 1]")
        out["confidence"] = conf

    return out


def load_turn_restrictions_json(path: str | Path) -> list[dict[str, Any]]:
    """Read a manual turn-restrictions file and normalize every entry.

    The JSON root may be either ``{"turn_restrictions": [...]}`` (optionally
    with ``format_version``) or a bare list. Missing ``id`` values are filled
    with ``tr_manual_{idx:04d}`` and missing ``source`` defaults to
    ``"manual"``.
    """
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        items: list[Any] = raw
    elif isinstance(raw, dict):
        items_obj = raw.get("turn_restrictions", [])
        if not isinstance(items_obj, list):
            raise TypeError("'turn_restrictions' must be a list")
        items = items_obj
    else:
        raise TypeError("turn_restrictions JSON root must be an object or a list")

    return [
        _coerce_item(item, index=i, default_source="manual", id_prefix="tr_manual_")
        for i, item in enumerate(items)
    ]


def turn_restrictions_from_camera_detections(
    observations: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract ``kind == 'turn_restriction'`` entries from camera observations.

    Observations without a ``junction_node_id`` are skipped (a bare ``edge_id``
    is not enough to place a restriction at a specific junction). Missing
    ``id`` values are filled with ``tr_camera_{idx:04d}`` and missing
    ``source`` defaults to ``"camera_detection"``.
    """
    out: list[dict[str, Any]] = []
    idx = 0
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        if obs.get("kind") != "turn_restriction":
            continue
        if not isinstance(obs.get("junction_node_id"), str) or not obs["junction_node_id"]:
            continue
        out.append(
            _coerce_item(
                obs,
                index=idx,
                default_source="camera_detection",
                id_prefix="tr_camera_",
            )
        )
        idx += 1
    return out


def merge_turn_restrictions(*groups: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Concatenate groups, dedupe by ``id`` (first occurrence wins), preserve order."""
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for group in groups:
        if group is None:
            continue
        for entry in group:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            if not isinstance(entry_id, str) or not entry_id:
                continue
            if entry_id in seen:
                continue
            seen.add(entry_id)
            merged.append(entry)
    return merged


__all__ = [
    "ALLOWED_DIRECTIONS",
    "ALLOWED_RESTRICTIONS",
    "load_turn_restrictions_json",
    "merge_turn_restrictions",
    "turn_restrictions_from_camera_detections",
]
