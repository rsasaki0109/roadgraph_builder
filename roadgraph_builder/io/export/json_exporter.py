"""JSON export of the road graph (intermediate for SD/HD map pipelines)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roadgraph_builder.core.graph.graph import Graph


def json_document_payload(
    data: Any,
    *,
    indent: int = 2,
    compact: bool = False,
) -> str:
    """Return a UTF-8 JSON document payload with the repository's trailing newline."""
    if compact:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    else:
        payload = json.dumps(data, ensure_ascii=False, indent=indent)
    return payload + "\n"


def write_json_document(
    data: Any,
    path: str | Path,
    *,
    indent: int = 2,
    compact: bool = False,
) -> None:
    """Write a JSON document, preserving pretty output by default."""
    Path(path).write_text(json_document_payload(data, indent=indent, compact=compact), encoding="utf-8")


def export_graph_json(
    graph: Graph,
    path: str | Path,
    *,
    indent: int = 2,
    compact: bool = False,
) -> None:
    """Write graph to UTF-8 JSON."""
    write_json_document(graph.to_dict(), path, indent=indent, compact=compact)
