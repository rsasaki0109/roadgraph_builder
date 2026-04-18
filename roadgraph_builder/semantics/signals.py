"""Infer candidate signalized junctions from stop patterns in a GPS trace.

A simple heuristic: detect stop windows (consecutive samples with median speed
below a threshold held for a minimum duration), take the centroid of each stop,
snap to the nearest graph node, and count how many stop events anchor at each
node. Nodes that accumulate ``min_stops`` or more independent stop events get
marked as signalized candidates.

This is not a ground-truth traffic-signal detector — it captures anywhere a
driver has repeatedly stopped, which includes signals, stop signs, congestion
hot-spots, and parking pauses. The intent is to surface *candidate* signal
locations that downstream review can confirm.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from roadgraph_builder.routing.nearest import nearest_node
from roadgraph_builder.routing.trip_reconstruction import _detect_stop_windows

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.io.trajectory.loader import Trajectory


@dataclass(frozen=True)
class StopEvent:
    """One detected stop window anchored at a graph node."""

    start_index: int
    end_index: int
    duration_s: float
    centroid_xy_m: tuple[float, float]
    node_id: str
    distance_m: float


def detect_stop_events(
    graph: "Graph",
    traj: "Trajectory",
    *,
    stop_speed_mps: float = 0.8,
    stop_min_duration_s: float = 30.0,
    max_distance_m: float = 20.0,
) -> list[StopEvent]:
    """Return every stop window paired with the nearest graph node."""
    ts = traj.timestamps
    xy = traj.xy
    windows = _detect_stop_windows(
        ts,
        xy,
        stop_speed_mps=stop_speed_mps,
        stop_min_duration_s=stop_min_duration_s,
    )
    events: list[StopEvent] = []
    for start, end in windows:
        xs = [float(xy[i][0]) for i in range(start, end + 1)]
        ys = [float(xy[i][1]) for i in range(start, end + 1)]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        try:
            nn = nearest_node(graph, x_m=cx, y_m=cy)
        except ValueError:
            continue
        if nn.distance_m > max_distance_m:
            continue
        events.append(
            StopEvent(
                start_index=start,
                end_index=end,
                duration_s=float(ts[end] - ts[start]),
                centroid_xy_m=(cx, cy),
                node_id=nn.node_id,
                distance_m=nn.distance_m,
            )
        )
    return events


def infer_signalized_junctions(
    graph: "Graph",
    traj: "Trajectory",
    *,
    stop_speed_mps: float = 0.8,
    stop_min_duration_s: float = 30.0,
    max_distance_m: float = 20.0,
    min_stops: int = 2,
) -> dict[str, int]:
    """Tag nodes with ``signalized_candidate = true`` when enough stops anchor there.

    Writes ``attributes.signalized_candidate`` (bool),
    ``attributes.stop_event_count`` (int), and
    ``attributes.stop_event_total_seconds`` (float) on qualifying nodes.
    Returns a ``{node_id: stop_count}`` dict for the newly-labelled nodes.
    """
    events = detect_stop_events(
        graph,
        traj,
        stop_speed_mps=stop_speed_mps,
        stop_min_duration_s=stop_min_duration_s,
        max_distance_m=max_distance_m,
    )
    counts: dict[str, int] = {}
    durations: dict[str, float] = {}
    for ev in events:
        counts[ev.node_id] = counts.get(ev.node_id, 0) + 1
        durations[ev.node_id] = durations.get(ev.node_id, 0.0) + ev.duration_s

    labelled: dict[str, int] = {}
    for n in graph.nodes:
        c = counts.get(n.id, 0)
        if c >= min_stops:
            if not isinstance(n.attributes, dict):
                n.attributes = {}
            n.attributes["signalized_candidate"] = True
            n.attributes["stop_event_count"] = c
            n.attributes["stop_event_total_seconds"] = durations.get(n.id, 0.0)
            labelled[n.id] = c
    return labelled


__all__ = ["StopEvent", "detect_stop_events", "infer_signalized_junctions"]
