"""Fuse multiple independent trajectories into per-edge observation stats.

``build --extra-csv`` concatenates several CSVs before building the graph, so
they share centerlines when they overlap. Trace fusion is the complementary
analytics step: keep a **fixed graph** and, for every separate trajectory
(typically one drive / one day), accumulate coverage counts, time-of-day
exposure, and first / last observation timestamps on each edge it touches.

After a multi-day batch the graph nodes + edges encode a coverage map: edges
seen by many traces are the dependable backbone; edges seen once are still
candidates that the builder hasn't fully validated.

This runs on top of :func:`snap_trajectory_to_graph` for speed / simplicity —
downstream consumers that prefer the HMM decoder can substitute it before
aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable

from roadgraph_builder.routing.map_match import snap_trajectory_to_graph

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.io.trajectory.loader import Trajectory


@dataclass
class EdgeObservationStats:
    """Mutable per-edge stats updated by :func:`fuse_traces_into_graph`."""

    trace_observation_count: int = 0
    matched_samples: int = 0
    first_observed_timestamp: float | None = None
    last_observed_timestamp: float | None = None
    observed_hour_bins: dict[int, int] = field(default_factory=dict)
    observed_weekday_bins: dict[int, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "trace_observation_count": self.trace_observation_count,
            "matched_samples": self.matched_samples,
            "first_observed_timestamp": self.first_observed_timestamp,
            "last_observed_timestamp": self.last_observed_timestamp,
            "observed_hour_bins": {str(k): v for k, v in sorted(self.observed_hour_bins.items())},
            "observed_weekday_bins": {str(k): v for k, v in sorted(self.observed_weekday_bins.items())},
        }


def _bins_from_timestamp(ts: float) -> tuple[int | None, int | None]:
    """Return ``(hour, weekday)`` bins when the timestamp looks epoch-like."""
    # Anything > 10^9 is interpreted as unix seconds (post 2001-09-09).
    if ts < 1_000_000_000:
        return None, None
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None, None
    return dt.hour, dt.weekday()


def fuse_traces_into_graph(
    graph: "Graph",
    trajectories: Iterable["Trajectory"],
    *,
    snap_max_distance_m: float = 15.0,
) -> dict[str, EdgeObservationStats]:
    """Accumulate per-edge observation stats across ``trajectories``.

    Each trajectory is snapped independently. For every edge any trajectory
    sample snaps onto:

    - ``trace_observation_count`` increments by 1 (a single trajectory counts
      once regardless of how many samples it contributed).
    - ``matched_samples`` accumulates the raw matched sample count.
    - ``first_observed_timestamp`` / ``last_observed_timestamp`` track the
      envelope across all contributing samples (trajectory timestamps).
    - ``observed_hour_bins`` / ``observed_weekday_bins`` bucket the sample
      timestamps by UTC hour-of-day and weekday when the value looks like an
      epoch second. Non-epoch timestamps (e.g. normalized floats starting at
      0) are skipped for binning but still accumulated elsewhere.

    Every edge in the graph gets a ``attributes.trace_stats`` dict (even if
    zero observations), so downstream consumers can scan uniformly.
    Returns a ``{edge_id: EdgeObservationStats}`` map for the caller.
    """
    stats: dict[str, EdgeObservationStats] = {e.id: EdgeObservationStats() for e in graph.edges}

    for traj in trajectories:
        ts_arr = traj.timestamps
        snapped = snap_trajectory_to_graph(graph, traj.xy, max_distance_m=snap_max_distance_m)
        touched_this_trace: set[str] = set()
        for i, s in enumerate(snapped):
            if s is None:
                continue
            edge_stats = stats[s.edge_id]
            edge_stats.matched_samples += 1
            ts = float(ts_arr[i])
            if edge_stats.first_observed_timestamp is None or ts < edge_stats.first_observed_timestamp:
                edge_stats.first_observed_timestamp = ts
            if edge_stats.last_observed_timestamp is None or ts > edge_stats.last_observed_timestamp:
                edge_stats.last_observed_timestamp = ts
            h, wd = _bins_from_timestamp(ts)
            if h is not None:
                edge_stats.observed_hour_bins[h] = edge_stats.observed_hour_bins.get(h, 0) + 1
            if wd is not None:
                edge_stats.observed_weekday_bins[wd] = edge_stats.observed_weekday_bins.get(wd, 0) + 1
            touched_this_trace.add(s.edge_id)
        for eid in touched_this_trace:
            stats[eid].trace_observation_count += 1

    for e in graph.edges:
        if not isinstance(e.attributes, dict):
            e.attributes = {}
        e.attributes["trace_stats"] = stats[e.id].as_dict()

    return stats


def coverage_buckets(stats: dict[str, EdgeObservationStats]) -> dict[str, int]:
    """Group edges by how many independent traces touched them.

    Returns ``{"0": N0, "1": N1, "2_plus": N2plus, "5_plus": N5plus}``.
    Handy for a quick coverage summary.
    """
    buckets = {"0": 0, "1": 0, "2_plus": 0, "5_plus": 0}
    for st in stats.values():
        c = st.trace_observation_count
        if c == 0:
            buckets["0"] += 1
        elif c == 1:
            buckets["1"] += 1
        if c >= 2:
            buckets["2_plus"] += 1
        if c >= 5:
            buckets["5_plus"] += 1
    return buckets


__all__ = [
    "EdgeObservationStats",
    "coverage_buckets",
    "fuse_traces_into_graph",
]
