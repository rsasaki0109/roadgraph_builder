"""Load precomputed camera / perception labels keyed by edge id (JSON)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from roadgraph_builder.core.graph.graph import Graph


def load_camera_detections_json(path: str | Path) -> list[dict[str, Any]]:
    """Parse a detections file and return the ``observations`` list.

    Expected shape::

        {"format_version": 1, "observations": [ {...}, ... ]}

    Each observation should include at least ``edge_id`` and ``kind``; other
    keys are preserved (e.g. ``value_kmh``, ``confidence``).
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("detections JSON root must be an object")
    obs = raw.get("observations", [])
    if not isinstance(obs, list):
        raise TypeError("observations must be a list")
    return [cast(dict[str, Any], o) for o in obs if isinstance(o, dict)]


def apply_camera_detections_to_graph(graph: Graph, observations: list[dict[str, Any]]) -> Graph:
    """Merge observations into each edge's ``attributes.hd.semantic_rules`` (list of dicts)."""
    by_edge: dict[str, list[dict[str, Any]]] = {}
    for o in observations:
        eid = o.get("edge_id")
        if eid is None:
            continue
        sid = str(eid)
        by_edge.setdefault(sid, []).append(dict(o))

    for e in graph.edges:
        extra = by_edge.get(e.id)
        if not extra:
            continue
        attrs = dict(e.attributes)
        hd = attrs.get("hd")
        if not isinstance(hd, dict):
            hd = {}
        else:
            hd = dict(hd)
        existing = hd.get("semantic_rules")
        rules: list[dict[str, Any]] = []
        if isinstance(existing, list):
            for x in existing:
                if isinstance(x, dict):
                    rules.append(dict(x))
        rules.extend(extra)
        hd["semantic_rules"] = rules
        attrs["hd"] = hd
        e.attributes = attrs

    graph.metadata = {
        **graph.metadata,
        "camera_detections": {
            "observation_count": len(observations),
            "edges_touched": len(by_edge),
        },
    }
    return graph
