"""Map OSM ``type=restriction`` relations onto our graph's edges.

The ``export-bundle --turn-restrictions-json`` input is keyed by **our**
``node_id`` / ``edge_id`` namespace (see ``navigation/turn_restrictions.py``).
OSM restriction relations instead reference OSM ``(from_way, via_node, to_way)``.
This module bridges the two by snapping the via-node onto the nearest graph
node and picking incident edges whose tangent at the junction best aligns
with each OSM way's direction away from the via-node.

Typical usage::

    overpass = load_overpass_json("/tmp/paris_turn_restrictions_raw.json")
    result = convert_osm_restrictions_to_graph(graph, overpass)
    write_json({"format_version": 1, "turn_restrictions": result.restrictions}, ...)

The conversion is a best-effort spatial match. Unmatched restrictions go into
``result.skipped`` with a reason string so callers can surface the miss rate.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence, cast

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.utils.geo import lonlat_to_meters


_OSM_TO_GRAPH_RESTRICTION = {
    "no_left_turn": "no_left_turn",
    "no_right_turn": "no_right_turn",
    "no_straight_on": "no_straight",
    "no_u_turn": "no_u_turn",
    "only_left_turn": "only_left",
    "only_right_turn": "only_right",
    "only_straight_on": "only_straight",
}


@dataclass
class OsmRestrictionConversion:
    """Result of ``convert_osm_restrictions_to_graph``."""

    restrictions: list[dict[str, object]] = field(default_factory=list)
    skipped: list[dict[str, object]] = field(default_factory=list)


def load_overpass_json(path: str | Path) -> dict[str, object]:
    """Read a raw Overpass response produced by ``scripts/fetch_osm_turn_restrictions.py``."""
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(f"Overpass JSON root must be an object: {p}")
    return cast(dict[str, object], raw)


def _origin_from_graph(graph: Graph) -> tuple[float, float]:
    meta = graph.metadata or {}
    origin = meta.get("map_origin")
    if isinstance(origin, dict) and "lat0" in origin and "lon0" in origin:
        return float(origin["lat0"]), float(origin["lon0"])  # type: ignore[arg-type]
    raise KeyError(
        "Graph metadata.map_origin must contain lat0/lon0 to convert OSM restrictions. "
        "Rebuild with export-bundle / build (both populate it) or pass origin_lat/origin_lon."
    )


def _unit(vx: float, vy: float) -> tuple[float, float]:
    n = math.hypot(vx, vy)
    if n < 1e-12:
        return 0.0, 0.0
    return vx / n, vy / n


@dataclass
class _IncidentEdge:
    edge_id: str
    direction: str  # "forward" when start_node == junction, else "reverse"
    other_node_id: str
    away_unit: tuple[float, float]  # tangent pointing away from the junction


class OsmRestrictionMapper:
    """Hold the graph + projected OSM elements and expose a per-relation mapper.

    The class precomputes:
    - graph node positions (meters in the graph's local ENU frame),
    - per-node incident edges and their unit tangents at the junction,
    - OSM node lat/lon → meter projections,
    - OSM way -> node ref list.

    Call :meth:`convert` with a single relation dict (Overpass shape) to get a
    ``turn_restrictions`` entry or a skip reason.
    """

    def __init__(
        self,
        graph: Graph,
        overpass: dict[str, object],
        *,
        max_snap_distance_m: float = 25.0,
        min_edge_tangent_alignment: float = 0.3,
    ) -> None:
        self.graph = graph
        self.max_snap_distance_m = float(max_snap_distance_m)
        self.min_edge_tangent_alignment = float(min_edge_tangent_alignment)
        self.lat0, self.lon0 = _origin_from_graph(graph)

        elements = overpass.get("elements", [])
        if not isinstance(elements, list):
            raise TypeError("Overpass 'elements' must be a list")

        self._osm_nodes_xy: dict[int, tuple[float, float]] = {}
        self._osm_ways: dict[int, list[int]] = {}
        for el in elements:
            if not isinstance(el, dict):
                continue
            kind = el.get("type")
            if kind == "node":
                nid = el.get("id")
                lat = el.get("lat")
                lon = el.get("lon")
                if isinstance(nid, int) and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    x, y = lonlat_to_meters(float(lon), float(lat), self.lat0, self.lon0)
                    self._osm_nodes_xy[nid] = (x, y)
            elif kind == "way":
                wid = el.get("id")
                refs = el.get("nodes")
                if isinstance(wid, int) and isinstance(refs, list):
                    self._osm_ways[wid] = [int(r) for r in refs if isinstance(r, int)]

        self._node_xy: dict[str, tuple[float, float]] = {
            n.id: (float(n.position[0]), float(n.position[1])) for n in graph.nodes
        }

        self._incident: dict[str, list[_IncidentEdge]] = {nid: [] for nid in self._node_xy}
        for edge in graph.edges:
            poly = edge.polyline
            if poly is None or len(poly) < 2:
                continue
            fx, fy = poly[0]
            sx, sy = poly[1]
            lx, ly = poly[-1]
            px, py = poly[-2]
            start_away = _unit(float(sx) - float(fx), float(sy) - float(fy))
            end_away = _unit(float(px) - float(lx), float(py) - float(ly))
            sid = edge.start_node_id
            eid = edge.end_node_id
            if sid in self._incident and start_away != (0.0, 0.0):
                self._incident[sid].append(
                    _IncidentEdge(edge.id, "forward", eid, start_away)
                )
            if eid in self._incident and end_away != (0.0, 0.0):
                self._incident[eid].append(
                    _IncidentEdge(edge.id, "reverse", sid, end_away)
                )

    def _nearest_node(self, x: float, y: float) -> tuple[str | None, float]:
        best_id: str | None = None
        best_d2 = float("inf")
        for nid, (nx, ny) in self._node_xy.items():
            d2 = (nx - x) * (nx - x) + (ny - y) * (ny - y)
            if d2 < best_d2:
                best_d2 = d2
                best_id = nid
        return best_id, math.sqrt(best_d2) if best_id is not None else float("inf")

    def _way_direction_away_from_via(
        self, way_id: int, via_node_id: int
    ) -> tuple[float, float] | None:
        refs = self._osm_ways.get(way_id)
        if refs is None or via_node_id not in refs or len(refs) < 2:
            return None

        via_xy = self._osm_nodes_xy.get(via_node_id)
        if via_xy is None:
            return None
        vx, vy = via_xy

        # Find the adjacent vertex on this way that is not the via node. Prefer
        # the immediate neighbour(s); if the via sits in the interior, both
        # sides are candidates — pick the closer one, since restrictions in
        # Paris virtually always have the via at an endpoint of the way.
        idx_list = [i for i, r in enumerate(refs) if r == via_node_id]
        candidates: list[int] = []
        for idx in idx_list:
            if idx - 1 >= 0:
                candidates.append(refs[idx - 1])
            if idx + 1 < len(refs):
                candidates.append(refs[idx + 1])
        if not candidates:
            return None

        best_vec: tuple[float, float] | None = None
        best_d = float("inf")
        for neighbour_id in candidates:
            nxy = self._osm_nodes_xy.get(neighbour_id)
            if nxy is None:
                continue
            nx, ny = nxy
            dx = nx - vx
            dy = ny - vy
            d = math.hypot(dx, dy)
            if d < 1e-6:
                continue
            if d < best_d:
                best_d = d
                best_vec = (dx / d, dy / d)
        return best_vec

    def _pick_edge(
        self,
        junction_node_id: str,
        want_unit: tuple[float, float],
        *,
        exclude_edge: str | None,
    ) -> _IncidentEdge | None:
        best: _IncidentEdge | None = None
        best_score = -2.0
        for inc in self._incident.get(junction_node_id, []):
            if exclude_edge is not None and inc.edge_id == exclude_edge:
                continue
            score = inc.away_unit[0] * want_unit[0] + inc.away_unit[1] * want_unit[1]
            if score > best_score:
                best_score = score
                best = inc
        if best is None or best_score < self.min_edge_tangent_alignment:
            return None
        return best

    def convert(
        self, relation: dict[str, Any], *, index: int, id_prefix: str = "tr_osm_"
    ) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        """Return ``(restriction_entry, None)`` on success or ``(None, skip_info)``."""
        tags = relation.get("tags") or {}
        if not isinstance(tags, dict):
            tags = {}
        osm_restriction = tags.get("restriction")
        mapped_restriction = _OSM_TO_GRAPH_RESTRICTION.get(osm_restriction or "")
        rel_id = relation.get("id")

        def skip(reason: str) -> tuple[None, dict[str, object]]:
            return None, {
                "osm_relation_id": rel_id,
                "osm_restriction": osm_restriction,
                "reason": reason,
            }

        if mapped_restriction is None:
            return skip(f"unsupported restriction tag '{osm_restriction!r}'")

        members = relation.get("members") or []
        if not isinstance(members, list):
            return skip("relation has no members list")

        from_way_id: int | None = None
        to_way_id: int | None = None
        via_node_id: int | None = None
        via_is_way = False
        for m in members:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            ref = m.get("ref")
            typ = m.get("type")
            if not isinstance(ref, int):
                continue
            if role == "from" and typ == "way":
                from_way_id = ref
            elif role == "to" and typ == "way":
                to_way_id = ref
            elif role == "via" and typ == "node":
                via_node_id = ref
            elif role == "via" and typ == "way":
                via_is_way = True

        if via_is_way and via_node_id is None:
            return skip("way-via restrictions not supported yet")
        if from_way_id is None or to_way_id is None or via_node_id is None:
            return skip("incomplete from/via/to members")

        via_xy = self._osm_nodes_xy.get(via_node_id)
        if via_xy is None:
            return skip(f"via node {via_node_id} not in fetched node set")

        junction_node_id, snap_d = self._nearest_node(*via_xy)
        if junction_node_id is None or snap_d > self.max_snap_distance_m:
            return skip(
                f"via node {via_node_id} did not snap to graph (nearest {snap_d:.1f} m > {self.max_snap_distance_m} m)"
            )

        from_dir = self._way_direction_away_from_via(from_way_id, via_node_id)
        to_dir = self._way_direction_away_from_via(to_way_id, via_node_id)
        if from_dir is None or to_dir is None:
            return skip("could not compute away-from-via direction for from_way/to_way")

        from_inc = self._pick_edge(junction_node_id, from_dir, exclude_edge=None)
        if from_inc is None:
            return skip(
                "no incident edge aligns with from_way direction "
                f"(junction {junction_node_id}, tangent alignment < {self.min_edge_tangent_alignment})"
            )
        # U-turns share the same way for from/to; the graph's from-edge is
        # often the best match for the to-side as well (just traversed in
        # the opposite direction). Allow from_edge == to_edge for that case.
        allow_same_edge = (
            mapped_restriction == "no_u_turn" or from_way_id == to_way_id
        )
        to_inc = self._pick_edge(
            junction_node_id,
            to_dir,
            exclude_edge=None if allow_same_edge else from_inc.edge_id,
        )
        if to_inc is None:
            return skip(
                "no incident edge aligns with to_way direction distinct from the from-edge"
            )

        # from_direction semantics: how we traverse from_edge to *arrive at* the junction.
        # - from_inc.direction == "forward": away_unit was taken at the edge's start_node,
        #   i.e. start_node == junction. Arriving at the junction therefore means traversing
        #   end_node → start_node (reverse of digitization).
        from_direction = "reverse" if from_inc.direction == "forward" else "forward"
        # to_direction semantics: how we traverse to_edge when *leaving* the junction.
        # - to_inc.direction == "forward": start_node == junction, so leaving means start→end → "forward".
        to_direction = "forward" if to_inc.direction == "forward" else "reverse"

        entry: dict[str, object] = {
            "id": f"{id_prefix}{index:04d}",
            "junction_node_id": junction_node_id,
            "from_edge_id": from_inc.edge_id,
            "from_direction": from_direction,
            "to_edge_id": to_inc.edge_id,
            "to_direction": to_direction,
            "restriction": mapped_restriction,
            "source": "osm",
        }
        if rel_id is not None:
            entry["confidence"] = 0.8
            entry["_osm_relation_id"] = int(rel_id)
        return entry, None


def convert_osm_restrictions_to_graph(
    graph: Graph,
    overpass: dict[str, object],
    *,
    max_snap_distance_m: float = 25.0,
    min_edge_tangent_alignment: float = 0.3,
    id_prefix: str = "tr_osm_",
) -> OsmRestrictionConversion:
    """Map every restriction relation in ``overpass`` onto ``graph`` edges.

    Args:
        graph: Target graph (with ``metadata.map_origin``).
        overpass: Parsed Overpass JSON (``load_overpass_json`` output).
        max_snap_distance_m: Max distance from projected via-node to the nearest
            graph node. Beyond this the restriction is skipped.
        min_edge_tangent_alignment: Minimum ``cos(angle)`` between an incident
            edge's tangent and the OSM way's direction away from the via-node
            for the edge to be accepted.
        id_prefix: Prefix for the generated ``turn_restrictions`` ids.

    Returns:
        :class:`OsmRestrictionConversion` with both accepted entries and
        per-relation skip reasons. The accepted entries carry an extra
        ``_osm_relation_id`` field (leading underscore → stripped before
        validation; see ``_strip_private`` callers) that callers can drop
        before handing the list to ``merge_turn_restrictions``.
    """
    mapper = OsmRestrictionMapper(
        graph,
        overpass,
        max_snap_distance_m=max_snap_distance_m,
        min_edge_tangent_alignment=min_edge_tangent_alignment,
    )
    elements = cast(Sequence[object], overpass.get("elements") or [])
    relations = [
        cast(dict[str, Any], el)
        for el in elements
        if isinstance(el, dict) and el.get("type") == "relation"
    ]
    accepted: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    idx = 0
    for rel in relations:
        entry, skip = mapper.convert(rel, index=idx, id_prefix=id_prefix)
        if entry is not None:
            accepted.append(entry)
            idx += 1
        elif skip is not None:
            skipped.append(skip)
    return OsmRestrictionConversion(restrictions=accepted, skipped=skipped)


def strip_private_fields(entries: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """Drop underscore-prefixed keys so the output passes ``turn_restrictions.schema.json``."""
    cleaned: list[dict[str, object]] = []
    for entry in entries:
        cleaned.append({k: v for k, v in entry.items() if not k.startswith("_")})
    return cleaned


__all__ = [
    "OsmRestrictionConversion",
    "OsmRestrictionMapper",
    "convert_osm_restrictions_to_graph",
    "load_overpass_json",
    "strip_private_fields",
]
