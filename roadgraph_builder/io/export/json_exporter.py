"""JSON export of the road graph (intermediate for SD/HD map pipelines)."""

from __future__ import annotations

import json
from pathlib import Path

from roadgraph_builder.core.graph.graph import Graph


def export_graph_json(graph: Graph, path: str | Path, *, indent: int = 2) -> None:
    """Write graph to UTF-8 JSON."""
    path = Path(path)
    path.write_text(json.dumps(graph.to_dict(), ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")
