"""Turn-by-turn navigation guidance from a route GeoJSON + sd_nav.

Converts a route_geojson (FeatureCollection produced by build_route_geojson)
together with sd_nav.json into a sequential list of GuidanceStep objects,
each carrying a human-readable maneuver description and a heading-change
angle. No ML, no map tiles — deterministic from the graph geometry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

MANEUVER_CATEGORIES = (
    "depart",
    "arrive",
    "straight",
    "slight_left",
    "left",
    "sharp_left",
    "slight_right",
    "right",
    "sharp_right",
    "u_turn",
    "continue",
)


@dataclass(frozen=True)
class GuidanceStep:
    """One step in a turn-by-turn navigation sequence.

    Attributes:
        step_index: 0-based position in the sequence.
        edge_id: Graph edge id this step covers.
        start_distance_m: Cumulative distance from route start at the
            beginning of this edge.
        length_m: Length of this edge in meters.
        maneuver_at_end: Maneuver category at the end of this edge
            (from MANEUVER_CATEGORIES).
        heading_change_deg: Signed heading change in degrees at the end of
            this edge (+right / −left). 0 for arrive/depart.
        junction_type_at_end: Value of junction_type attribute of the end
            node (may be None when absent or last step).
        description: Short English description ("Turn right onto e42").
        sd_nav_edge_maneuvers: allowed_maneuvers list from sd_nav for this
            edge (forward direction), empty when sd_nav lacks the edge.
    """

    step_index: int
    edge_id: str
    start_distance_m: float
    length_m: float
    maneuver_at_end: str
    heading_change_deg: float
    junction_type_at_end: str | None
    description: str
    sd_nav_edge_maneuvers: list[str]


def _heading_deg(dx: float, dy: float) -> float:
    """Compass heading in degrees: 0=East, 90=North (standard math angle)."""
    return math.degrees(math.atan2(dy, dx))


def _signed_heading_change(h1_deg: float, h2_deg: float) -> float:
    """Signed angular difference h2 - h1 in (−180, +180].

    Positive = right turn, negative = left turn (standard math convention
    where +y is left in a right-hand coordinate frame). Actually:
    standard convention for navigation: positive = right, negative = left.
    Cross product sign determines this: v_in × v_out > 0 means left turn.
    """
    diff = h2_deg - h1_deg
    while diff > 180.0:
        diff -= 360.0
    while diff <= -180.0:
        diff += 360.0
    return diff


def _categorize_maneuver(
    heading_change_deg: float,
    *,
    slight_deg: float = 20.0,
    sharp_deg: float = 120.0,
    u_turn_deg: float = 165.0,
) -> str:
    """Map a signed heading change to a MANEUVER_CATEGORIES string."""
    abs_h = abs(heading_change_deg)
    if abs_h >= u_turn_deg:
        return "u_turn"
    # Negative = left turn, positive = right turn.
    if heading_change_deg < 0:
        # Left family.
        if abs_h >= sharp_deg:
            return "sharp_left"
        if abs_h >= slight_deg:
            return "left"
        return "straight"
    else:
        # Right family.
        if abs_h >= sharp_deg:
            return "sharp_right"
        if abs_h >= slight_deg:
            return "right"
        return "straight"


def _edge_exit_heading(coords: list[list[float]]) -> float | None:
    """Heading (degrees, math convention) at the end of a coordinate sequence."""
    if len(coords) < 2:
        return None
    x1, y1 = coords[-2][0], coords[-2][1]
    x2, y2 = coords[-1][0], coords[-1][1]
    dx, dy = x2 - x1, y2 - y1
    if math.hypot(dx, dy) < 1e-9:
        return None
    return _heading_deg(dx, dy)


def _edge_entry_heading(coords: list[list[float]]) -> float | None:
    """Heading (degrees, math convention) at the start of a coordinate sequence."""
    if len(coords) < 2:
        return None
    x1, y1 = coords[0][0], coords[0][1]
    x2, y2 = coords[1][0], coords[1][1]
    dx, dy = x2 - x1, y2 - y1
    if math.hypot(dx, dy) < 1e-9:
        return None
    return _heading_deg(dx, dy)


def _describe_maneuver(maneuver: str, edge_id: str) -> str:
    """Short English description for a maneuver."""
    map_ = {
        "depart": f"Depart on {edge_id}",
        "arrive": f"Arrive at destination on {edge_id}",
        "straight": f"Continue straight on {edge_id}",
        "continue": f"Continue on {edge_id}",
        "slight_left": f"Bear left onto {edge_id}",
        "left": f"Turn left onto {edge_id}",
        "sharp_left": f"Sharp left onto {edge_id}",
        "slight_right": f"Bear right onto {edge_id}",
        "right": f"Turn right onto {edge_id}",
        "sharp_right": f"Sharp right onto {edge_id}",
        "u_turn": f"Make a U-turn onto {edge_id}",
    }
    return map_.get(maneuver, f"Proceed on {edge_id}")


def build_guidance(
    route_geojson: dict,
    sd_nav: dict,
    *,
    slight_deg: float = 20.0,
    sharp_deg: float = 120.0,
    u_turn_deg: float = 165.0,
) -> list[GuidanceStep]:
    """Build a turn-by-turn guidance sequence from a route GeoJSON and sd_nav.

    Processes the per-edge LineString features in route_geojson (produced by
    build_route_geojson / write_route_geojson). For each consecutive pair of
    edges, computes the heading change at the shared junction and maps it to a
    MANEUVER_CATEGORIES label. Looks up sd_nav for edge-level allowed_maneuvers.

    Returns a list of GuidanceStep — one per edge in the route, starting with
    "depart" and ending with "arrive".
    """
    # Build a quick index of sd_nav edges.
    sd_nav_index: dict[str, list[str]] = {}
    for sd_edge in sd_nav.get("edges", []):
        eid = sd_edge.get("edge_id", "")
        maneuvers = sd_edge.get("allowed_maneuvers", [])
        if eid and isinstance(maneuvers, list):
            sd_nav_index[eid] = [str(m) for m in maneuvers]

    # Extract per-edge features (LineStrings with edge_id property).
    features = route_geojson.get("features", [])
    edge_features: list[dict] = []
    for f in features:
        if not isinstance(f, dict):
            continue
        geom = f.get("geometry", {})
        props = f.get("properties", {}) or {}
        if geom.get("type") == "LineString" and props.get("edge_id"):
            edge_features.append(f)

    if not edge_features:
        return []

    steps: list[GuidanceStep] = []
    cumulative_m = 0.0

    for i, feat in enumerate(edge_features):
        props = feat.get("properties", {}) or {}
        geom = feat.get("geometry", {})
        edge_id = str(props.get("edge_id", f"edge_{i}"))
        junction_type_at_end: str | None = props.get("junction_type_at_end") or None  # type: ignore[assignment]
        coords = geom.get("coordinates", [])

        sd_maneuvers = sd_nav_index.get(edge_id, [])

        # Compute length from properties or from coordinates.
        if "length_m" in props:
            length_m = float(props["length_m"])
        elif len(coords) >= 2:
            length_m = sum(
                math.hypot(coords[k + 1][0] - coords[k][0], coords[k + 1][1] - coords[k][1])
                for k in range(len(coords) - 1)
            )
        else:
            length_m = 0.0

        # Determine maneuver at the END of this edge.
        is_first = i == 0
        is_last = i == len(edge_features) - 1

        heading_change = 0.0
        if is_first:
            maneuver = "depart"
        elif is_last:
            maneuver = "arrive"
        else:
            # Compute heading change between previous edge exit and this edge entry.
            prev_coords = edge_features[i - 1].get("geometry", {}).get("coordinates", [])
            prev_exit = _edge_exit_heading(prev_coords)
            this_entry = _edge_entry_heading(coords)
            if prev_exit is not None and this_entry is not None:
                heading_change = _signed_heading_change(prev_exit, this_entry)
                # Negate: in standard math coords, left = positive cross product,
                # but for navigation, right = positive.
                # atan2(dy,dx): v_in = [cos(h1), sin(h1)], v_out = [cos(h2), sin(h2)]
                # cross = sin(h2-h1) > 0 means left of direction of travel.
                # We want positive = right turn.
                heading_change = -heading_change
            maneuver = _categorize_maneuver(
                heading_change,
                slight_deg=slight_deg,
                sharp_deg=sharp_deg,
                u_turn_deg=u_turn_deg,
            )

        description = _describe_maneuver(maneuver, edge_id)

        step = GuidanceStep(
            step_index=i,
            edge_id=edge_id,
            start_distance_m=cumulative_m,
            length_m=length_m,
            maneuver_at_end=maneuver,
            heading_change_deg=heading_change,
            junction_type_at_end=junction_type_at_end,
            description=description,
            sd_nav_edge_maneuvers=sd_maneuvers,
        )
        steps.append(step)
        cumulative_m += length_m

    return steps


__all__ = ["GuidanceStep", "MANEUVER_CATEGORIES", "build_guidance"]
