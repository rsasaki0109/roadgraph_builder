"""Reconstruct individual trips from a long GPS trace matched to a graph.

Takes a trajectory (timestamps + xy) and the built graph, snaps each sample to
an edge (nearest-edge by default), then partitions the sequence into **trips**
separated by:

- **time gaps** — ``Δt`` between consecutive samples exceeds ``max_time_gap_s``
- **spatial gaps** — ``Δs`` Euclidean distance exceeds ``max_spatial_gap_m``
- **stops** — a contiguous window where the median speed falls below
  ``stop_speed_mps`` for at least ``stop_min_duration_s``

Each trip is reported with its start / end timestamps, start / end matched edge,
the ordered edge sequence visited, total distance along those edges, duration,
and mean speed. Useful as a first step for trip analytics (coverage, ETA
baselining) on public GPS dumps that concatenate many drivers / days.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from roadgraph_builder.routing.map_match import snap_trajectory_to_graph

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.io.trajectory.loader import Trajectory


@dataclass(frozen=True)
class Trip:
    """One reconstructed trip segment."""

    trip_id: int
    start_index: int
    end_index: int
    start_timestamp: float
    end_timestamp: float
    duration_s: float
    start_xy_m: tuple[float, float]
    end_xy_m: tuple[float, float]
    start_edge_id: str | None
    end_edge_id: str | None
    edge_sequence: list[str]
    sample_count: int
    matched_sample_count: int
    total_distance_m: float
    mean_speed_mps: float


def _speed_between(
    ts: float, next_ts: float, xy: tuple[float, float], next_xy: tuple[float, float]
) -> float:
    import math

    dt = next_ts - ts
    if dt <= 0:
        return 0.0
    return math.hypot(next_xy[0] - xy[0], next_xy[1] - xy[1]) / dt


def _detect_stop_windows(
    timestamps,
    xy,
    *,
    stop_speed_mps: float,
    stop_min_duration_s: float,
) -> list[tuple[int, int]]:
    """Return ``(start_idx, end_idx_inclusive)`` ranges of stop windows."""
    if len(timestamps) < 2:
        return []
    stops: list[tuple[int, int]] = []
    n = len(timestamps)
    i = 0
    while i < n - 1:
        if _speed_between(float(timestamps[i]), float(timestamps[i + 1]), tuple(xy[i]), tuple(xy[i + 1])) < stop_speed_mps:
            j = i
            while j + 1 < n and _speed_between(
                float(timestamps[j]), float(timestamps[j + 1]), tuple(xy[j]), tuple(xy[j + 1])
            ) < stop_speed_mps:
                j += 1
            duration = float(timestamps[j]) - float(timestamps[i])
            if duration >= stop_min_duration_s:
                stops.append((i, j))
            i = j + 1
        else:
            i += 1
    return stops


def reconstruct_trips(
    graph: "Graph",
    traj: "Trajectory",
    *,
    max_time_gap_s: float = 300.0,
    max_spatial_gap_m: float = 200.0,
    stop_speed_mps: float = 0.8,
    stop_min_duration_s: float = 60.0,
    min_trip_samples: int = 3,
    min_trip_distance_m: float = 10.0,
    snap_max_distance_m: float = 20.0,
) -> list[Trip]:
    """Partition a trajectory into trips based on gaps, stops, and graph snapping.

    Trajectory samples must be in the graph's meter frame. Use
    ``load_multi_trajectory_csvs`` upstream to combine several CSVs sharing
    one origin; the resulting gaps between files become natural trip
    boundaries.
    """
    import math

    timestamps = traj.timestamps
    xy = traj.xy
    n = len(timestamps)
    if n == 0:
        return []

    snapped = snap_trajectory_to_graph(graph, xy, max_distance_m=snap_max_distance_m)

    # Mark split points: a split happens BETWEEN sample i and i+1 when a gap
    # or a stop ends there. Index the break points as "after index k".
    break_after: set[int] = set()
    for i in range(n - 1):
        dt = float(timestamps[i + 1] - timestamps[i])
        ds = math.hypot(float(xy[i + 1][0] - xy[i][0]), float(xy[i + 1][1] - xy[i][1]))
        if dt > max_time_gap_s or ds > max_spatial_gap_m:
            break_after.add(i)

    for start, end in _detect_stop_windows(
        timestamps,
        xy,
        stop_speed_mps=stop_speed_mps,
        stop_min_duration_s=stop_min_duration_s,
    ):
        # Close the prior trip at the start of the stop and the next trip
        # begins after the stop ends.
        if start > 0:
            break_after.add(start - 1)
        if end < n - 1:
            break_after.add(end)

    # Walk the samples building candidate trips.
    trips: list[Trip] = []
    trip_start = 0
    current_trip_id = 0

    def _emit_trip(lo: int, hi: int) -> None:
        nonlocal current_trip_id
        if hi < lo:
            return
        sample_count = hi - lo + 1
        matched = [snapped[i] for i in range(lo, hi + 1) if snapped[i] is not None]
        if sample_count < min_trip_samples:
            return
        edge_sequence: list[str] = []
        for s in matched:
            if s is None:
                continue
            if not edge_sequence or edge_sequence[-1] != s.edge_id:
                edge_sequence.append(s.edge_id)
        total_dist = 0.0
        for i in range(lo, hi):
            total_dist += math.hypot(
                float(xy[i + 1][0] - xy[i][0]),
                float(xy[i + 1][1] - xy[i][1]),
            )
        if total_dist < min_trip_distance_m:
            return
        duration = float(timestamps[hi] - timestamps[lo])
        mean_speed = (total_dist / duration) if duration > 0 else 0.0
        trips.append(
            Trip(
                trip_id=current_trip_id,
                start_index=lo,
                end_index=hi,
                start_timestamp=float(timestamps[lo]),
                end_timestamp=float(timestamps[hi]),
                duration_s=duration,
                start_xy_m=(float(xy[lo][0]), float(xy[lo][1])),
                end_xy_m=(float(xy[hi][0]), float(xy[hi][1])),
                start_edge_id=(matched[0].edge_id if matched else None),
                end_edge_id=(matched[-1].edge_id if matched else None),
                edge_sequence=edge_sequence,
                sample_count=sample_count,
                matched_sample_count=len(matched),
                total_distance_m=total_dist,
                mean_speed_mps=mean_speed,
            )
        )
        current_trip_id += 1

    for i in range(n - 1):
        if i in break_after:
            _emit_trip(trip_start, i)
            trip_start = i + 1
    _emit_trip(trip_start, n - 1)
    return trips


def trip_stats_summary(trips: list[Trip]) -> dict:
    if not trips:
        return {"trip_count": 0, "total_distance_m": 0.0, "total_duration_s": 0.0}
    total_dist = sum(t.total_distance_m for t in trips)
    total_dur = sum(t.duration_s for t in trips)
    total_samples = sum(t.sample_count for t in trips)
    total_matched = sum(t.matched_sample_count for t in trips)
    return {
        "trip_count": len(trips),
        "total_distance_m": total_dist,
        "total_duration_s": total_dur,
        "total_samples": total_samples,
        "matched_samples": total_matched,
        "matched_ratio": (total_matched / total_samples) if total_samples else 0.0,
        "mean_distance_m": total_dist / len(trips),
        "mean_duration_s": total_dur / len(trips),
    }


__all__ = ["Trip", "reconstruct_trips", "trip_stats_summary"]
