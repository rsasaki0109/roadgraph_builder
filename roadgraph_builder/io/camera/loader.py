"""Camera observation loaders (MVP: stubs)."""

from __future__ import annotations

from pathlib import Path


def load_camera_observations_placeholder(path: str | Path) -> None:
    """Reserved for image sequences + calibration or precomputed detections JSON."""
    raise NotImplementedError(
        "Camera ingestion is not implemented yet. Extend pipeline with fusion module."
    )
