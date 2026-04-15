"""Semantic annotations (lane type, rules, signals) — separate from geometry.

Graph geometry lives in `core.graph`; this package will hold typed semantics and
validators for `Edge.attributes` / `Node` extensions.

TODO: bind traffic signals / stop lines from camera pipelines.
TODO: lane connectivity and maneuver rules for HD maps.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class LaneKind(str, Enum):
    """Placeholder lane classification for future SD/HD pipelines."""

    UNKNOWN = "unknown"
    DRIVING = "driving"
    # TODO: BIKING, BOUNDARY, etc.


def attach_lane_kind(edge_attributes: dict[str, Any], kind: LaneKind) -> dict[str, Any]:
    """Merge lane kind into a copy of edge attributes (non-destructive)."""
    out = dict(edge_attributes)
    out["lane_kind"] = kind.value
    return out
