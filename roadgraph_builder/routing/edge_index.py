"""Spatial projection index for snapping points to graph edge polylines."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from roadgraph_builder.routing._core import edge_cache_signature

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph

_MAX_SEGMENT_CELL_FOOTPRINT = 1024


@dataclass(frozen=True)
class EdgeProjection:
    """Closest projection of a point onto one graph edge."""

    edge_id: str
    projection_xy_m: tuple[float, float]
    distance_m: float
    arc_length_m: float
    edge_length_m: float


@dataclass(frozen=True)
class _EdgeSegment:
    edge_order: int
    segment_order: int
    edge_id: str
    ax: float
    ay: float
    bx: float
    by: float
    abx: float
    aby: float
    ab2: float
    segment_length_m: float
    arc_start_m: float
    edge_length_m: float
    min_x: float
    min_y: float
    max_x: float
    max_y: float


@dataclass(frozen=True)
class _ProjectionHit:
    projection: EdgeProjection
    distance_sq: float
    edge_order: int
    segment_order: int


@dataclass(frozen=True)
class EdgeProjectionIndex:
    """Spatial hash cache for repeated nearest-edge projection lookups."""

    signature: tuple[object, ...]
    cell_size_m: float
    min_x: float
    min_y: float
    cells: dict[tuple[int, int], tuple[int, ...]]
    overflow_segments: tuple[int, ...]
    segments: tuple[_EdgeSegment, ...]

    def nearest_projection(
        self,
        x_m: float,
        y_m: float,
        max_distance_m: float,
    ) -> EdgeProjection | None:
        """Return the nearest edge projection inside ``max_distance_m``."""

        best: _ProjectionHit | None = None
        for hit in self._iter_hits(float(x_m), float(y_m), float(max_distance_m)):
            if best is None or _hit_key(hit) < _hit_key(best):
                best = hit
        return best.projection if best is not None else None

    def candidate_projections(
        self,
        x_m: float,
        y_m: float,
        radius_m: float,
        *,
        limit: int | None = None,
    ) -> list[EdgeProjection]:
        """Return one best projection per edge inside ``radius_m``.

        Results are ordered by distance, with graph edge order preserving
        legacy tie-breaking. ``limit`` keeps only the nearest N edges.
        """

        best_by_edge: dict[str, _ProjectionHit] = {}
        for hit in self._iter_hits(float(x_m), float(y_m), float(radius_m)):
            existing = best_by_edge.get(hit.projection.edge_id)
            if existing is None or _hit_key(hit) < _hit_key(existing):
                best_by_edge[hit.projection.edge_id] = hit

        hits = sorted(best_by_edge.values(), key=_hit_key)
        if limit is not None:
            hits = hits[: max(0, int(limit))]
        return [hit.projection for hit in hits]

    def _iter_hits(self, x: float, y: float, radius: float):
        if not self.segments:
            return
        if radius <= 0.0:
            return

        radius_is_bounded = math.isfinite(radius)
        radius_sq = radius * radius if radius_is_bounded else math.inf
        seen: set[int] = set()
        if radius_is_bounded:
            for segment_index in self._segment_indices_for_radius(x, y, radius):
                if segment_index in seen:
                    continue
                seen.add(segment_index)
                hit = _project_on_segment(self.segments[segment_index], x, y, radius_sq)
                if hit is not None:
                    yield hit
        else:
            for segment_index in range(len(self.segments)):
                hit = _project_on_segment(self.segments[segment_index], x, y, radius_sq)
                if hit is not None:
                    yield hit

        for segment_index in self.overflow_segments:
            if segment_index in seen:
                continue
            hit = _project_on_segment(self.segments[segment_index], x, y, radius_sq)
            if hit is not None:
                yield hit

    def _segment_indices_for_radius(self, x: float, y: float, radius: float):
        ix0 = _cell_index(x - radius, self.min_x, self.cell_size_m)
        ix1 = _cell_index(x + radius, self.min_x, self.cell_size_m)
        iy0 = _cell_index(y - radius, self.min_y, self.cell_size_m)
        iy1 = _cell_index(y + radius, self.min_y, self.cell_size_m)
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                yield from self.cells.get((ix, iy), ())


def project_point_on_polyline(
    px: float,
    py: float,
    poly,
) -> tuple[float, tuple[float, float], float, float]:
    """Closest point on ``poly``.

    Returns ``(distance, projection_xy, arc_length_at_projection,
    total_length)`` and preserves the legacy first-segment tie-break.
    """

    if len(poly) < 2:
        return (float("inf"), (0.0, 0.0), 0.0, 0.0)
    best_d_sq = math.inf
    best_pt = (0.0, 0.0)
    best_arc = 0.0
    cum = 0.0
    for i in range(len(poly) - 1):
        ax, ay = float(poly[i][0]), float(poly[i][1])
        bx, by = float(poly[i + 1][0]), float(poly[i + 1][1])
        abx = bx - ax
        aby = by - ay
        ab2 = abx * abx + aby * aby
        if ab2 < 1e-18:
            t = 0.0
            qx, qy = ax, ay
        else:
            t = ((px - ax) * abx + (py - ay) * aby) / ab2
            t = max(0.0, min(1.0, t))
            qx = ax + t * abx
            qy = ay + t * aby
        dx = px - qx
        dy = py - qy
        d_sq = dx * dx + dy * dy
        seg_len = math.hypot(abx, aby)
        if d_sq < best_d_sq:
            best_d_sq = d_sq
            best_pt = (qx, qy)
            best_arc = cum + t * seg_len
        cum += seg_len
    return math.sqrt(best_d_sq), best_pt, best_arc, cum


def get_edge_projection_index(graph: "Graph") -> EdgeProjectionIndex:
    """Return a graph-local projection index, rebuilding after edge mutations."""

    signature = _edge_index_signature(graph)
    cached = getattr(graph, "_edge_projection_index_cache", None)
    if isinstance(cached, EdgeProjectionIndex) and cached.signature == signature:
        return cached
    index = _build_edge_projection_index(graph, signature)
    try:
        setattr(graph, "_edge_projection_index_cache", index)
    except Exception:
        pass
    return index


def _edge_index_signature(graph: "Graph") -> tuple[object, ...]:
    return (
        id(graph.edges),
        len(graph.edges),
        tuple(edge_cache_signature(edge) for edge in graph.edges),
    )


def _build_edge_projection_index(
    graph: "Graph",
    signature: tuple[object, ...],
) -> EdgeProjectionIndex:
    edge_segments: list[_EdgeSegment] = []
    for edge_order, edge in enumerate(graph.edges):
        poly = edge.polyline
        if len(poly) < 2:
            continue
        lengths: list[float] = []
        edge_length = 0.0
        for i in range(len(poly) - 1):
            ax, ay = float(poly[i][0]), float(poly[i][1])
            bx, by = float(poly[i + 1][0]), float(poly[i + 1][1])
            seg_len = math.hypot(bx - ax, by - ay)
            lengths.append(seg_len)
            edge_length += seg_len

        arc = 0.0
        for segment_order, seg_len in enumerate(lengths):
            ax, ay = float(poly[segment_order][0]), float(poly[segment_order][1])
            bx, by = float(poly[segment_order + 1][0]), float(poly[segment_order + 1][1])
            abx = bx - ax
            aby = by - ay
            edge_segments.append(
                _EdgeSegment(
                    edge_order=edge_order,
                    segment_order=segment_order,
                    edge_id=str(edge.id),
                    ax=ax,
                    ay=ay,
                    bx=bx,
                    by=by,
                    abx=abx,
                    aby=aby,
                    ab2=abx * abx + aby * aby,
                    segment_length_m=seg_len,
                    arc_start_m=arc,
                    edge_length_m=edge_length,
                    min_x=min(ax, bx),
                    min_y=min(ay, by),
                    max_x=max(ax, bx),
                    max_y=max(ay, by),
                )
            )
            arc += seg_len

    if not edge_segments:
        return EdgeProjectionIndex(
            signature=signature,
            cell_size_m=1.0,
            min_x=0.0,
            min_y=0.0,
            cells={},
            overflow_segments=(),
            segments=(),
        )

    min_x = min(segment.min_x for segment in edge_segments)
    max_x = max(segment.max_x for segment in edge_segments)
    min_y = min(segment.min_y for segment in edge_segments)
    max_y = max(segment.max_y for segment in edge_segments)
    width = max_x - min_x
    height = max_y - min_y
    area = max(width * height, 1.0)
    nominal_spacing = math.sqrt(area / max(len(edge_segments), 1))
    cell_size_m = max(nominal_spacing * 4.0, 1.0)

    mutable_cells: dict[tuple[int, int], list[int]] = {}
    overflow: list[int] = []
    for segment_index, segment in enumerate(edge_segments):
        ix0 = _cell_index(segment.min_x, min_x, cell_size_m)
        ix1 = _cell_index(segment.max_x, min_x, cell_size_m)
        iy0 = _cell_index(segment.min_y, min_y, cell_size_m)
        iy1 = _cell_index(segment.max_y, min_y, cell_size_m)
        footprint = (ix1 - ix0 + 1) * (iy1 - iy0 + 1)
        if footprint > _MAX_SEGMENT_CELL_FOOTPRINT:
            overflow.append(segment_index)
            continue
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                mutable_cells.setdefault((ix, iy), []).append(segment_index)

    cells = {key: tuple(values) for key, values in mutable_cells.items()}
    return EdgeProjectionIndex(
        signature=signature,
        cell_size_m=cell_size_m,
        min_x=min_x,
        min_y=min_y,
        cells=cells,
        overflow_segments=tuple(overflow),
        segments=tuple(edge_segments),
    )


def _cell_index(value: float, origin: float, cell_size: float) -> int:
    return math.floor((value - origin) / cell_size)


def _hit_key(hit: _ProjectionHit) -> tuple[float, int, int]:
    return (hit.distance_sq, hit.edge_order, hit.segment_order)


def _bbox_distance_sq(segment: _EdgeSegment, x: float, y: float) -> float:
    dx = 0.0
    if x < segment.min_x:
        dx = segment.min_x - x
    elif x > segment.max_x:
        dx = x - segment.max_x
    dy = 0.0
    if y < segment.min_y:
        dy = segment.min_y - y
    elif y > segment.max_y:
        dy = y - segment.max_y
    return dx * dx + dy * dy


def _project_on_segment(
    segment: _EdgeSegment,
    px: float,
    py: float,
    radius_sq: float,
) -> _ProjectionHit | None:
    if _bbox_distance_sq(segment, px, py) >= radius_sq:
        return None

    if segment.ab2 < 1e-18:
        t = 0.0
        qx, qy = segment.ax, segment.ay
    else:
        t = (
            (px - segment.ax) * segment.abx
            + (py - segment.ay) * segment.aby
        ) / segment.ab2
        t = max(0.0, min(1.0, t))
        qx = segment.ax + t * segment.abx
        qy = segment.ay + t * segment.aby
    dx = px - qx
    dy = py - qy
    distance_sq = dx * dx + dy * dy
    if distance_sq >= radius_sq:
        return None

    projection = EdgeProjection(
        edge_id=segment.edge_id,
        projection_xy_m=(qx, qy),
        distance_m=math.sqrt(distance_sq),
        arc_length_m=segment.arc_start_m + t * segment.segment_length_m,
        edge_length_m=segment.edge_length_m,
    )
    return _ProjectionHit(
        projection=projection,
        distance_sq=distance_sq,
        edge_order=segment.edge_order,
        segment_order=segment.segment_order,
    )


__all__ = [
    "EdgeProjection",
    "EdgeProjectionIndex",
    "get_edge_projection_index",
    "project_point_on_polyline",
]
