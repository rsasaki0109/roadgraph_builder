"""Lanelet2 export (placeholder).

TODO: map Node/Edge + semantics to lanelets/areas; write OSM XML or lanelet2 format.
"""

from __future__ import annotations

from pathlib import Path

from roadgraph_builder.core.graph.graph import Graph


def export_lanelet2(_graph: Graph, _path: str | Path) -> None:
    """Write a Lanelet2-compatible representation to disk (not implemented)."""
    raise NotImplementedError(
        "Lanelet2 export is not implemented yet. Use export_graph_json() for MVP JSON."
    )
