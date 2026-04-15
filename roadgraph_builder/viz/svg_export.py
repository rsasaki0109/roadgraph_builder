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

    title = "Road graph preview (trajectory samples + centerlines + nodes)"
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<defs>',
        '<linearGradient id="bgGrad" x1="0" y1="0" x2="0" y2="1">',
        '<stop offset="0%" stop-color="#f8fafc"/>',
        '<stop offset="100%" stop-color="#e2e8f0"/>',
        "</linearGradient>",
        '<filter id="edgeGlow" x="-20%" y="-20%" width="140%" height="140%">',
        '<feGaussianBlur stdDeviation="0.8" result="b"/>',
        "<feMerge><feMergeNode in=\"b\"/><feMergeNode in=\"SourceGraphic\"/></feMerge>",
        "</filter>",
        '<style type="text/css"><![CDATA[.muted{fill:#64748b;font-size:11px;font-family:ui-sans-serif,system-ui,sans-serif}]]></style>',
        "</defs>",
        '<rect width="100%" height="100%" fill="url(#bgGrad)"/>',
        f'<text x="12" y="22" class="muted" font-size="13" font-weight="600" fill="#0f172a">{title}</text>',
        f'<text x="12" y="{height - 8:.0f}" class="muted">Local XY · span ≈ {w:.0f} × {h:.0f} m (same units as input)</text>',
        '<g stroke="#cbd5e1" stroke-width="0.5">',
    ]
    # Light grid for map-like readability
    for i in range(11):
        gx = width * i / 10
        gy = height * i / 10
        lines.append(f'<line x1="{gx:.1f}" y1="0" x2="{gx:.1f}" y2="{height}" />')
        lines.append(f'<line x1="0" y1="{gy:.1f}" x2="{width}" y2="{gy:.1f}" />')
    lines.extend(
        [
            "</g>",
            '<g stroke-linecap="round" stroke-linejoin="round">',
            '<g transform="translate(' + str(width - 188) + ',28)">',
            '<rect x="0" y="-14" width="176" height="72" rx="4" fill="white" stroke="#e2e8f0"/>',
            '<line x1="8" y1="8" x2="32" y2="8" stroke="#2563eb" stroke-width="3"/>',
            '<text x="40" y="12" class="muted">Centerline</text>',
            '<circle cx="20" cy="28" r="3" fill="#94a3b8"/>',
            '<text x="40" y="32" class="muted">Trajectory</text>',
            '<circle cx="20" cy="48" r="5" fill="#dc2626" stroke="#fff" stroke-width="1.2"/>',
            '<text x="40" y="52" class="muted">Node</text>',
            "</g>",
        ]
    )

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
                f'<path d="{d}" fill="none" stroke="#1d4ed8" stroke-width="3" opacity="0.98" '
                f'stroke-linecap="round" filter="url(#edgeGlow)"/>'
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
