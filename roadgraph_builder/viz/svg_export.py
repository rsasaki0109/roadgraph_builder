"""Export trajectory + road graph as SVG (no matplotlib).

Styling aims for a readable “map-like” diagram: not aerial imagery, but clearer road structure.
"""

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


def _nice_scale_meters(span: float) -> float:
    """Pick a round scale-bar length (meters) for ~10–15% of span."""
    if span <= 0:
        return 1.0
    target = span * 0.12
    for step in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000):
        if step >= target * 0.35:
            return float(step)
    return float(span * 0.2)


def write_trajectory_graph_svg(
    traj: Trajectory,
    graph: Graph,
    path: str | Path,
    *,
    width: float = 900,
    height: float = 700,
    margin_ratio: float = 0.08,
) -> None:
    """Write an SVG: trajectory (line + dots), road-shaped edges, nodes, scale bar."""
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

    scale_m = _nice_scale_meters(max(w, h))
    bar_px = scale_m / max(w, 1e-9) * width

    title = "Road structure preview"
    subtitle = "Trajectory + inferred centerlines + nodes (diagram, not satellite imagery)"

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        "<defs>",
        '<linearGradient id="bgGrad" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#f0fdf4"/>',
        '<stop offset="50%" stop-color="#f8fafc"/>',
        '<stop offset="100%" stop-color="#e0f2fe"/>',
        "</linearGradient>",
        '<filter id="edgeGlow" x="-30%" y="-30%" width="160%" height="160%">',
        '<feGaussianBlur stdDeviation="1.0" result="b"/>',
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>',
        "</filter>",
        '<style type="text/css"><![CDATA[',
        ".lbl{font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif}",
        ".sub{fill:#475569;font-size:11px}",
        "]]></style>",
        "</defs>",
        '<rect width="100%" height="100%" fill="url(#bgGrad)"/>',
        f'<text x="14" y="26" class="lbl" font-size="15" font-weight="700" fill="#0f172a">{title}</text>',
        f'<text x="14" y="44" class="sub">{subtitle}</text>',
        f'<text x="14" y="{height - 10:.0f}" class="sub">Span ≈ {w:.0f} × {h:.0f} (input units) · same projection as CSV</text>',
    ]

    # Grid (major / minor)
    lines.append('<g opacity="0.45" stroke="#94a3b8" stroke-width="0.35">')
    for i in range(21):
        gx = width * i / 20
        sw = 0.9 if i % 5 == 0 else 0.35
        lines.append(
            f'<line x1="{gx:.1f}" y1="0" x2="{gx:.1f}" y2="{height}" stroke-width="{sw}"/>'
        )
    for i in range(21):
        gy = height * i / 20
        sw = 0.9 if i % 5 == 0 else 0.35
        lines.append(
            f'<line x1="0" y1="{gy:.1f}" x2="{width}" y2="{gy:.1f}" stroke-width="{sw}"/>'
        )
    lines.append("</g>")

    lines.append('<g stroke-linecap="round" stroke-linejoin="round">')

    # Trajectory as a faint polyline + dots (reads as “driven path”)
    if traj.xy.shape[0] >= 2:
        tpts = [(float(traj.xy[i, 0]), float(traj.xy[i, 1])) for i in range(traj.xy.shape[0])]
        td = path_d(tpts)
        lines.append(
            f'<path d="{td}" fill="none" stroke="#64748b" stroke-width="1.8" '
            f'stroke-opacity="0.35" stroke-linejoin="round"/>'
        )
    for x, y in traj.xy:
        cx, cy = tx(float(x)), ty(float(y))
        lines.append(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="1.6" fill="#475569" opacity="0.55"/>'
        )

    # Edges: “road” fill under centerline
    for e in graph.edges:
        if len(e.polyline) >= 2:
            d = path_d(e.polyline)
            lines.append(
                f'<path d="{d}" fill="none" stroke="#cbd5e1" stroke-width="11" '
                f'stroke-linecap="round" stroke-linejoin="round" opacity="0.95"/>'
            )
            lines.append(
                f'<path d="{d}" fill="none" stroke="#1e40af" stroke-width="3.2" '
                f'stroke-linecap="round" stroke-linejoin="round" opacity="0.95" filter="url(#edgeGlow)"/>'
            )

    # Nodes + labels
    for n in graph.nodes:
        x, y = n.position
        cx, cy = tx(x), ty(y)
        lines.append(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="6.5" fill="#b91c1c" stroke="#fff" stroke-width="2"/>'
        )
        lines.append(
            f'<text x="{cx + 10:.2f}" y="{cy - 10:.2f}" font-size="12" class="lbl" '
            f'fill="#0f172a" font-weight="600" stroke="#ffffff" stroke-width="0.6" '
            f'paint-order="stroke fill">{n.id}</text>'
        )

    # Scale bar (bottom-right)
    bx = width - bar_px - 24
    by = height - 28
    lines.append(
        f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_px:.1f}" height="5" rx="1" '
        f'fill="#1e293b" opacity="0.85"/>'
    )
    lines.append(
        f'<text x="{bx:.1f}" y="{by - 6:.1f}" class="sub" font-size="10" font-weight="600" fill="#334155">'
        f"≈ {scale_m:.0f} m</text>"
    )

    # Legend box
    lx = width - 200
    lines.extend(
        [
            f'<g transform="translate({lx},58)">',
            '<rect x="0" y="-18" width="188" height="92" rx="6" fill="#ffffff" stroke="#cbd5e1" '
            'stroke-width="1" opacity="0.96"/>',
            '<line x1="10" y1="8" x2="38" y2="8" stroke="#cbd5e1" stroke-width="9" stroke-linecap="round"/>',
            '<line x1="10" y1="8" x2="38" y2="8" stroke="#1e40af" stroke-width="3" stroke-linecap="round"/>',
            '<text x="48" y="12" class="sub" font-size="11" fill="#334155">Road (width + centerline)</text>',
            '<line x1="10" y1="32" x2="38" y2="32" stroke="#64748b" stroke-width="1.5" opacity="0.4"/>',
            '<text x="48" y="36" class="sub" font-size="11" fill="#334155">Raw trajectory</text>',
            '<circle cx="24" cy="56" r="5" fill="#b91c1c" stroke="#fff" stroke-width="1.5"/>',
            '<text x="48" y="60" class="sub" font-size="11" fill="#334155">Node</text>',
            "</g>",
        ]
    )

    lines.extend(["</g>", "</svg>"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
