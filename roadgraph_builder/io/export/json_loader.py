"""Load road graph JSON produced by ``export_graph_json`` / ``build``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from roadgraph_builder.core.graph.graph import Graph


def load_graph_json(path: str | Path) -> Graph:
    """Parse UTF-8 JSON and return a :class:`~roadgraph_builder.core.graph.graph.Graph`."""
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(f"JSON root must be object, got {type(raw).__name__}")
    return Graph.from_dict(cast(dict[str, object], raw))
