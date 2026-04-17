"""Summary statistics over a :class:`Graph` (edge lengths, bbox, junctions).

Downstream consumers — ``export-bundle`` manifests, the ``stats`` CLI, and
tuning scripts — all agree on one output shape here. Nothing in this module
mutates the graph.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph


def _polyline_length_m(pl: list[tuple[float, float]]) -> float:
    total = 0.0
    for i in range(len(pl) - 1):
        dx = float(pl[i + 1][0]) - float(pl[i][0])
        dy = float(pl[i + 1][1]) - float(pl[i][1])
        total += math.hypot(dx, dy)
    return total


def graph_stats(
    graph: Graph,
    *,
    origin_lat: float | None = None,
    origin_lon: float | None = None,
) -> dict[str, Any]:
    """Return ``edge_count`` / ``edge_length`` / ``bbox_m`` / ``bbox_wgs84_deg``.

    ``bbox_wgs84_deg`` is included only when both ``origin_lat`` / ``origin_lon``
    are provided, or when the graph carries a ``metadata.map_origin`` entry
    with ``lat0`` / ``lon0``. Otherwise the key is omitted.
    """
    lengths = [_polyline_length_m(e.polyline) for e in graph.edges]
    if lengths:
        srt = sorted(lengths)
        mid = len(srt) // 2
        if len(srt) % 2:
            median_len = float(srt[mid])
        else:
            median_len = 0.5 * float(srt[mid - 1] + srt[mid])
        edge_length = {
            "min_m": float(min(lengths)),
            "median_m": median_len,
            "max_m": float(max(lengths)),
            "total_m": float(sum(lengths)),
        }
    else:
        edge_length = {"min_m": 0.0, "median_m": 0.0, "max_m": 0.0, "total_m": 0.0}

    xs = [float(n.position[0]) for n in graph.nodes]
    ys = [float(n.position[1]) for n in graph.nodes]
    if xs and ys:
        bbox_m = {
            "x_min_m": min(xs),
            "y_min_m": min(ys),
            "x_max_m": max(xs),
            "y_max_m": max(ys),
        }
    else:
        bbox_m = {"x_min_m": 0.0, "y_min_m": 0.0, "x_max_m": 0.0, "y_max_m": 0.0}

    out: dict[str, Any] = {
        "edge_count": len(graph.edges),
        "node_count": len(graph.nodes),
        "edge_length": edge_length,
        "bbox_m": bbox_m,
    }

    if origin_lat is None or origin_lon is None:
        mo = graph.metadata.get("map_origin") if isinstance(graph.metadata, dict) else None
        if isinstance(mo, dict) and "lat0" in mo and "lon0" in mo:
            origin_lat = float(mo["lat0"])
            origin_lon = float(mo["lon0"])

    if origin_lat is not None and origin_lon is not None:
        from roadgraph_builder.utils.geo import meters_to_lonlat

        sw_lon, sw_lat = meters_to_lonlat(
            bbox_m["x_min_m"], bbox_m["y_min_m"], origin_lat, origin_lon
        )
        ne_lon, ne_lat = meters_to_lonlat(
            bbox_m["x_max_m"], bbox_m["y_max_m"], origin_lat, origin_lon
        )
        out["bbox_wgs84_deg"] = {
            "sw_lon": sw_lon,
            "sw_lat": sw_lat,
            "ne_lon": ne_lon,
            "ne_lat": ne_lat,
        }

    return out


def junction_stats(graph: Graph) -> dict[str, Any]:
    """Return ``total_nodes`` / ``hints`` / ``multi_branch_types`` counts."""
    hint_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    for n in graph.nodes:
        hint = n.attributes.get("junction_hint") if isinstance(n.attributes, dict) else None
        if isinstance(hint, str):
            hint_counts[hint] += 1
        jtype = n.attributes.get("junction_type") if isinstance(n.attributes, dict) else None
        if isinstance(jtype, str):
            type_counts[jtype] += 1
    return {
        "total_nodes": len(graph.nodes),
        "hints": dict(sorted(hint_counts.items())),
        "multi_branch_types": dict(sorted(type_counts.items())),
    }


__all__ = ["graph_stats", "junction_stats"]
