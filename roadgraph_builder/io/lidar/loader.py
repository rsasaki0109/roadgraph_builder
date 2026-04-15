"""LiDAR loaders (MVP: stubs for modular extension)."""

from __future__ import annotations

from pathlib import Path


def load_lidar_placeholder(path: str | Path) -> None:
    """Reserved entry point for future LiDAR ingestion (e.g. LAS/LAZ, numpy dumps).

    Will feed fusion / edge geometry updates; not used in trajectory-only MVP.
    """
    raise NotImplementedError(
        "LiDAR loading is not implemented yet. Use trajectory CSV via build_graph_from_csv()."
    )
