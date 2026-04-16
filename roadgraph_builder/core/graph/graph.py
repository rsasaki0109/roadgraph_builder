"""Container for nodes and edges (graph-first road structure)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.node import Node

# Bump when the JSON document shape changes incompatibly.
SCHEMA_VERSION = 1


@dataclass
class Graph:
    """Road topology as an attributed graph."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out

    @staticmethod
    def from_dict(data: dict[str, object]) -> "Graph":
        raw_nodes = data.get("nodes", [])
        raw_edges = data.get("edges", [])
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise TypeError("nodes and edges must be lists")
        sv = data.get("schema_version", SCHEMA_VERSION)
        if isinstance(sv, bool) or not isinstance(sv, int):
            raise TypeError(f"schema_version must be int, got {type(sv).__name__}")
        if sv != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version: {sv} (expected {SCHEMA_VERSION})")
        nodes_in = cast(list[Any], raw_nodes)
        edges_in = cast(list[Any], raw_edges)
        raw_meta = data.get("metadata", {})
        if raw_meta is None:
            meta: dict[str, object] = {}
        elif isinstance(raw_meta, dict):
            meta = dict(cast(dict[str, object], raw_meta))
        else:
            raise TypeError(f"metadata must be object or null, got {type(raw_meta).__name__}")
        return Graph(
            nodes=[Node.from_dict(cast(dict[str, object], n)) for n in nodes_in],
            edges=[Edge.from_dict(cast(dict[str, object], e)) for e in edges_in],
            metadata=dict(meta),
        )
