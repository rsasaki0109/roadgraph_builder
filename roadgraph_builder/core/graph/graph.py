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

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

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
        return Graph(
            nodes=[Node.from_dict(cast(dict[str, object], n)) for n in nodes_in],
            edges=[Edge.from_dict(cast(dict[str, object], e)) for e in edges_in],
        )
