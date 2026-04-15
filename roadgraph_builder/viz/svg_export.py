"""Export trajectory + road graph as a simple SVG (no matplotlib)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.io.trajectory.loader import Trajectory


def _collect_xy(traj: Trajectory, graph: Graph) -> np.ndarray:
    parts: list[np.ndarray] = [traj.xy]
    for n in graph.nodes:
        x, y = n.position
        parts.append(np.array([[x, y]], dtype=np.float64))
    for e in graph.edges:
        if e.polyline:
            parts.append(np.asarray(e.polyline, dtype=np.float64))
    return np.vstack(parts)


def write_trajectory_graph_svg(
    traj: Trajectory,
    graph: Graph,
    path: str | Path,
    *,
    width: float = 900,
    height: float = 700,
    margin_ratio: float = 0.08,
) -> None:
    """Write an SVG with raw trajectory, edge polylines, and nodes."""
    path = Path(path)
    pts = _collect_xy(traj, graph)
    if pts.shape[0] == 0:
        raise ValueError("Nothing to plot")

    xmin, ymin = float(pts.min(axis=0)[0]), float(pts.min(axis=0)[1])
    xmax, ymax = float(pts.max(axis=0)[0]), float(pts.max(axis=0)[1])
    dx = max(xmax - xmin, 1e-9)
    dy = max(ymax - ymin, 1e-9)
    mx = dx * margin_ratio
    my = dy * margin_ratio
    xmin -= mx
    xmax += mx
    ymin -= my
    ymax += my
    w = xmax - xmin
    h = ymax - ymin

    def tx(x: float) -> float:
        return (x - xmin) / w * width

    def ty(y: float) -> float:
        return height - (y - ymin) / h * height

    def path_d(points: list[tuple[float, float]]) -> str:
        if not points:
            return ""
        x0, y0 = points[0]
        parts = [f"M {tx(x0):.2f} {ty(y0):.2f}"]
        for x, y in points[1:]:
            parts.append(f"L {tx(x):.2f} {ty(y):.2f}")
        return " ".join(parts)

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fafafa"/>',
        '<g stroke-linecap="round" stroke-linejoin="round">',
    ]

    # Trajectory samples
    for x, y in traj.xy:
        cx, cy = tx(float(x)), ty(float(y))
        lines.append(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="2" fill="#94a3b8" opacity="0.85"/>'
        )

    # Edge centerlines
    for e in graph.edges:
        if len(e.polyline) >= 2:
            d = path_d(e.polyline)
            lines.append(
                f'<path d="{d}" fill="none" stroke="#2563eb" stroke-width="2.5" opacity="0.95"/>'
            )

    # Nodes
    for n in graph.nodes:
        x, y = n.position
        cx, cy = tx(x), ty(y)
        lines.append(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="5" fill="#dc2626" stroke="#fff" stroke-width="1.5"/>'
        )
        lines.append(
            f'<text x="{cx + 8:.2f}" y="{cy - 8:.2f}" font-size="11" font-family="sans-serif" fill="#334155">{n.id}</text>'
        )

    lines.extend(["</g>", "</svg>"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
