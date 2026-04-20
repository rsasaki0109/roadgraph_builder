"""Export a road graph to OSM XML 0.6 (WGS84) for Lanelet2 / JOSM-style tooling.

This writes **nodes**, **ways**, then **relations**. When an edge has both
``hd.lane_boundaries`` polylines, it also emits a Lanelet2-style **lanelet**
relation (``type=lanelet``) with ``left`` / ``right`` way members.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from xml.dom import minidom

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.utils.geo import meters_to_lonlat

_REGULATORY_SUBTYPES = frozenset(
    {
        "traffic_light",
        "stop_sign",
        "stop_line",
        "yield",
        "priority_right",
        "pedestrian_marking",
    }
)


def _fmt_lonlat(v: float) -> str:
    s = f"{v:.10f}"
    s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def _lanelet_tags_from_semantic_rules(rules: object) -> list[tuple[str, str]]:
    """Lanelet2-style tags from ``hd.semantic_rules`` (camera / fusion)."""
    out: list[tuple[str, str]] = []
    if not isinstance(rules, list):
        return out
    speeds: list[int] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        if r.get("kind") == "speed_limit" and "value_kmh" in r:
            try:
                speeds.append(int(float(r["value_kmh"])))
            except (TypeError, ValueError):
                continue
    if speeds:
        # Most restrictive (minimum) upper bound across observations.
        out.append(("speed_limit", str(min(speeds))))
    return out


def _emit_regulatory_elements_for_lanelet(
    rules: object,
    lanelet_relation_id: int,
    new_relation: Callable[[list[tuple[str, int, str]], list[tuple[str, str]]], int],
) -> None:
    """One ``regulatory_element`` relation per qualifying rule (Lanelet2-style)."""
    if not isinstance(rules, list):
        return
    for r in rules:
        if not isinstance(r, dict):
            continue
        kind = r.get("kind")
        if not isinstance(kind, str) or kind not in _REGULATORY_SUBTYPES:
            continue
        tags: list[tuple[str, str]] = [
            ("type", "regulatory_element"),
            ("subtype", kind),
            ("roadgraph:source", "semantic_rules"),
        ]
        if r.get("confidence") is not None:
            try:
                tags.append(("roadgraph:confidence", f"{float(r['confidence']):.4f}"))
            except (TypeError, ValueError):
                pass
        new_relation(
            [("relation", lanelet_relation_id, "refers")],
            tags,
        )


# ---------------------------------------------------------------------------
# δ. Lanelet2 fidelity helpers
# ---------------------------------------------------------------------------


def _speed_limit_tags(semantic_rules: list[dict]) -> list[tuple[str, str]]:
    """Extract speed limit tags from semantic_rules for regulatory_element export.

    Returns a list of (key, value) tag pairs for the fastest-match speed limit
    (minimum value_kmh across all speed_limit rules).
    """
    speeds: list[int] = []
    for r in semantic_rules:
        if not isinstance(r, dict):
            continue
        if r.get("kind") == "speed_limit" and "value_kmh" in r:
            try:
                speeds.append(int(float(r["value_kmh"])))
            except (TypeError, ValueError):
                continue
    if not speeds:
        return []
    return [("speed_limit", str(min(speeds))), ("type", "speed_limit")]


def _lane_marking_subtype(boundary_candidates: list[dict] | None) -> str:
    """Classify a set of lane-marking candidates as 'solid' or 'dashed'.

    Uses intensity_median and point_count density as a heuristic:
    - If any candidate has intensity_median >= 180 (bright paint) and
      a density >= 0.5 pts/m → 'solid'.
    - Otherwise → 'dashed'.
    Defaults to 'solid' when no candidates are supplied.
    """
    if not boundary_candidates:
        return "solid"
    for c in boundary_candidates:
        if not isinstance(c, dict):
            continue
        intensity = c.get("intensity_median", 0.0)
        point_count = c.get("point_count", 0)
        polyline = c.get("polyline_m", [])
        # Estimate polyline length.
        length_m = max(len(polyline) - 1, 1)  # rough lower bound
        density = point_count / length_m if length_m > 0 else 0.0
        if intensity >= 180 and density >= 0.5:
            return "solid"
    return "dashed"


def _build_traffic_light_regulatory(
    tl_rule: dict,
    lanelet_relation_id: int,
    new_node_fn,
    new_relation_fn,
    origin_lat: float,
    origin_lon: float,
) -> int | None:
    """Build a traffic_light regulatory_element relation.

    Returns the new relation id, or None if the rule lacks position data.
    The traffic light node is placed at world_xy_m if available.
    """
    world_xy = tl_rule.get("world_xy_m")
    if world_xy is None:
        return None

    from roadgraph_builder.utils.geo import meters_to_lonlat as _mtll
    if isinstance(world_xy, dict):
        x, y = float(world_xy.get("x", 0.0)), float(world_xy.get("y", 0.0))
    elif isinstance(world_xy, (list, tuple)) and len(world_xy) >= 2:
        x, y = float(world_xy[0]), float(world_xy[1])
    else:
        return None

    lon, lat = _mtll(x, y, origin_lat, origin_lon)
    tl_node_id = new_node_fn(lat, lon, {"type": "traffic_light"})
    members: list[tuple[str, int, str]] = [
        ("relation", lanelet_relation_id, "refers"),
        ("node", tl_node_id, "refers"),
    ]
    tags: list[tuple[str, str]] = [
        ("type", "regulatory_element"),
        ("subtype", "traffic_light"),
        ("roadgraph:source", "camera_detections"),
    ]
    conf = tl_rule.get("confidence")
    if conf is not None:
        try:
            tags.append(("roadgraph:confidence", f"{float(conf):.4f}"))
        except (TypeError, ValueError):
            pass
    return new_relation_fn(members, tags)


def _build_right_of_way_regulatory(
    turn_restriction: dict,
    lane_members: list[tuple[str, int, str]],
    new_relation_fn,
) -> int | None:
    """Build a right_of_way regulatory_element from a turn_restriction dict.

    Returns the new relation id or None when lane_members is empty.
    """
    if not lane_members:
        return None
    tags: list[tuple[str, str]] = [
        ("type", "regulatory_element"),
        ("subtype", "right_of_way"),
        ("roadgraph:source", "turn_restrictions"),
    ]
    restriction = turn_restriction.get("restriction", "")
    if isinstance(restriction, str):
        tags.append(("roadgraph:restriction", restriction))
    return new_relation_fn(lane_members, tags)


def _build_speed_limit_regulatory(
    speed_kmh: int,
    lanelet_relation_id: int,
    new_relation_fn,
) -> int:
    """Build a separate speed_limit regulatory_element relation (L2 spec style)."""
    members: list[tuple[str, int, str]] = [
        ("relation", lanelet_relation_id, "refers"),
    ]
    tags: list[tuple[str, str]] = [
        ("type", "regulatory_element"),
        ("subtype", "speed_limit"),
        ("speed_limit", str(speed_kmh)),
        ("roadgraph:source", "semantic_rules"),
    ]
    return new_relation_fn(members, tags)


# ---------------------------------------------------------------------------
# δ. validate_lanelet2_tags helper (used by CLI)
# ---------------------------------------------------------------------------


def validate_lanelet2_tags(osm_path: str | Path) -> tuple[list[str], list[str]]:
    """Parse an OSM XML file and check required Lanelet2 tags on lanelet relations.

    Required tags (per Lanelet2 spec): ``type=lanelet``, ``subtype``, ``location``,
    ``one_way`` (optional warning), ``speed_limit`` (optional warning).
    This function treats missing ``subtype`` or ``location`` as errors; missing
    ``speed_limit`` as a warning.

    Returns:
        (errors, warnings) — both lists of human-readable strings.
        If errors is non-empty, the caller should exit 1.
    """
    osm_path = Path(osm_path)
    tree = ET.parse(osm_path)
    root = tree.getroot()

    errors: list[str] = []
    warnings: list[str] = []

    for rel in root.findall("relation"):
        tags = {t.get("k"): t.get("v") for t in rel.findall("tag")}
        if tags.get("type") != "lanelet":
            continue
        rel_id = rel.get("id", "?")
        if not tags.get("subtype"):
            errors.append(f"relation {rel_id}: missing required tag 'subtype'")
        if not tags.get("location"):
            errors.append(f"relation {rel_id}: missing required tag 'location'")
        if not tags.get("speed_limit"):
            warnings.append(f"relation {rel_id}: no 'speed_limit' tag (informational)")

    return errors, warnings


def export_lanelet2_per_lane(
    graph: Graph,
    path: str | Path,
    *,
    origin_lat: float,
    origin_lon: float,
    generator: str = "roadgraph_builder",
) -> None:
    """Write per-lane Lanelet2 OSM XML using ``attributes.hd.lanes`` inferred by lane_inference.

    For edges that have ``attributes.hd.lane_count`` and ``attributes.hd.lanes``, this
    emits one lanelet relation per lane (with ``roadgraph:lane_index`` tag). Edges without
    ``hd.lanes`` fall back to the standard single-lanelet-per-edge output identical to
    :func:`export_lanelet2`.

    Adjacent lanelets on the same edge are linked with a ``type=regulatory_element,
    subtype=lane_change`` relation (one per pair).
    """
    path = Path(path)
    root = ET.Element("osm", version="0.6", generator=generator)

    next_id = 1
    node_children: list[ET.Element] = []
    way_children: list[ET.Element] = []
    relation_children: list[ET.Element] = []

    def new_node(lat: float, lon: float, tags: dict[str, str] | None = None) -> int:
        nonlocal next_id
        nid = next_id
        next_id += 1
        n_el = ET.Element("node", id=str(nid), lat=_fmt_lonlat(lat), lon=_fmt_lonlat(lon))
        if tags:
            for k, v in tags.items():
                ET.SubElement(n_el, "tag", k=k, v=v)
        node_children.append(n_el)
        return nid

    def new_way(nds: list[int], tags: list[tuple[str, str]]) -> int:
        nonlocal next_id
        w_id = next_id
        next_id += 1
        w_el = ET.Element("way", id=str(w_id))
        for nid in nds:
            ET.SubElement(w_el, "nd", ref=str(nid))
        for k, v in tags:
            ET.SubElement(w_el, "tag", k=k, v=v)
        way_children.append(w_el)
        return w_id

    def new_relation(members: list[tuple[str, int, str]], tags: list[tuple[str, str]]) -> int:
        nonlocal next_id
        r_id = next_id
        next_id += 1
        r_el = ET.Element("relation", id=str(r_id))
        for mtype, ref, role in members:
            ET.SubElement(r_el, "member", type=mtype, ref=str(ref), role=role)
        for k, v in tags:
            ET.SubElement(r_el, "tag", k=k, v=v)
        relation_children.append(r_el)
        return r_id

    # Graph-node export (same as standard).
    for n in graph.nodes:
        lon, lat = meters_to_lonlat(float(n.position[0]), float(n.position[1]), origin_lat, origin_lon)
        new_node(lat, lon, {"roadgraph": "graph_node", "roadgraph:node_id": str(n.id)})

    from roadgraph_builder.hd.boundaries import centerline_lane_boundaries

    for e in graph.edges:
        hd = e.attributes.get("hd") if isinstance(e.attributes.get("hd"), dict) else {}
        lanes_data = hd.get("lanes") if isinstance(hd, dict) else None
        lane_count = hd.get("lane_count") if isinstance(hd, dict) else None

        if lanes_data and isinstance(lanes_data, list) and len(lanes_data) >= 1:
            # Per-lane export: one lanelet per lane entry.
            half_width = hd.get("hd_refinement", {}).get("refined_half_width_m") if isinstance(hd.get("hd_refinement"), dict) else None
            if not half_width:
                half_width = 3.5 / 2.0
            lane_spacing = (2.0 * half_width) / max(len(lanes_data), 1)
            per_lane_half = lane_spacing / 2.0

            edge_lanelet_ids: list[int] = []
            for lane in lanes_data:
                if not isinstance(lane, dict):
                    continue
                lane_idx = lane.get("lane_index", 0)
                cl_pts = lane.get("centerline_m", [])
                # Build centerline polyline.
                cl_poly: list[tuple[float, float]] = []
                for pt in cl_pts:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        cl_poly.append((float(pt[0]), float(pt[1])))
                if len(cl_poly) < 2:
                    # Fall back to edge polyline offset.
                    from roadgraph_builder.hd.refinement import _shift_polyline
                    offset = lane.get("offset_m", 0.0)
                    cl_poly = _shift_polyline(e.polyline, float(offset))
                # Build left/right boundaries for this single lane.
                left_pts, right_pts = centerline_lane_boundaries(cl_poly, lane_spacing)
                if not left_pts or not right_pts or len(left_pts) < 2 or len(right_pts) < 2:
                    continue
                left_nds = []
                for x, y in left_pts:
                    lon, lat = meters_to_lonlat(float(x), float(y), origin_lat, origin_lon)
                    left_nds.append(new_node(lat, lon, None))
                right_nds = []
                for x, y in right_pts:
                    lon, lat = meters_to_lonlat(float(x), float(y), origin_lat, origin_lon)
                    right_nds.append(new_node(lat, lon, None))
                lw_id = new_way(left_nds, [
                    ("roadgraph", "lane_boundary"),
                    ("roadgraph:edge_id", str(e.id)),
                    ("roadgraph:lane_index", str(lane_idx)),
                    ("roadgraph:side", "left"),
                    ("type", "line_thin"),
                    ("subtype", "solid"),
                ])
                rw_id = new_way(right_nds, [
                    ("roadgraph", "lane_boundary"),
                    ("roadgraph:edge_id", str(e.id)),
                    ("roadgraph:lane_index", str(lane_idx)),
                    ("roadgraph:side", "right"),
                    ("type", "line_thin"),
                    ("subtype", "solid"),
                ])
                lanelet_tags: list[tuple[str, str]] = [
                    ("type", "lanelet"),
                    ("subtype", "road"),
                    ("location", "urban"),
                    ("roadgraph:edge_id", str(e.id)),
                    ("roadgraph:lane_index", str(lane_idx)),
                ]
                conf = lane.get("confidence")
                if conf is not None:
                    try:
                        lanelet_tags.append(("roadgraph:confidence", f"{float(conf):.4f}"))
                    except (TypeError, ValueError):
                        pass
                ll_id = new_relation(
                    [("way", lw_id, "left"), ("way", rw_id, "right")],
                    lanelet_tags,
                )
                edge_lanelet_ids.append(ll_id)

            # Emit lane_change relations for adjacent lanes.
            for i in range(len(edge_lanelet_ids) - 1):
                new_relation(
                    [
                        ("relation", edge_lanelet_ids[i], "lanelet"),
                        ("relation", edge_lanelet_ids[i + 1], "lanelet"),
                    ],
                    [
                        ("type", "regulatory_element"),
                        ("subtype", "lane_change"),
                        ("roadgraph:edge_id", str(e.id)),
                    ],
                )
        else:
            # Fallback: standard single-lanelet output for this edge.
            center_nd: list[int] = []
            for x, y in e.polyline:
                lon, lat = meters_to_lonlat(float(x), float(y), origin_lat, origin_lon)
                center_nd.append(new_node(lat, lon, None))
            center_way_id: int | None = None
            if len(center_nd) >= 2:
                center_way_id = new_way(center_nd, [
                    ("roadgraph", "centerline"),
                    ("roadgraph:edge_id", str(e.id)),
                    ("type", "line_thin"),
                    ("subtype", "solid"),
                ])
            left_way_id: int | None = None
            right_way_id: int | None = None
            if isinstance(hd, dict):
                lb = hd.get("lane_boundaries")
                if isinstance(lb, dict):
                    for side in ("left", "right"):
                        raw = lb.get(side)
                        if not isinstance(raw, list) or len(raw) < 2:
                            continue
                        nds: list[int] = []
                        for p in raw:
                            if not isinstance(p, dict):
                                continue
                            lon, lat = meters_to_lonlat(float(p["x"]), float(p["y"]), origin_lat, origin_lon)
                            nds.append(new_node(lat, lon, None))
                        if len(nds) < 2:
                            continue
                        wid = new_way(nds, [
                            ("roadgraph", "lane_boundary"),
                            ("roadgraph:edge_id", str(e.id)),
                            ("roadgraph:side", side),
                            ("type", "line_thin"),
                            ("subtype", "solid"),
                        ])
                        if side == "left":
                            left_way_id = wid
                        else:
                            right_way_id = wid
            if left_way_id is not None and right_way_id is not None:
                members: list[tuple[str, int, str]] = [
                    ("way", left_way_id, "left"),
                    ("way", right_way_id, "right"),
                ]
                if center_way_id is not None:
                    members.append(("way", center_way_id, "centerline"))
                hd_use = hd if isinstance(hd, dict) else {}
                ll_tags: list[tuple[str, str]] = [
                    ("type", "lanelet"),
                    ("subtype", "road"),
                    ("location", "urban"),
                    ("roadgraph:edge_id", str(e.id)),
                ]
                ll_tags.extend(_lanelet_tags_from_semantic_rules(hd_use.get("semantic_rules")))
                new_relation(members, ll_tags)

    for c in node_children:
        root.append(c)
    for c in way_children:
        root.append(c)
    for c in relation_children:
        root.append(c)

    xml_bytes = ET.tostring(root, encoding="utf-8")
    dom = minidom.parseString(xml_bytes)
    pretty = dom.toprettyxml(indent="  ", encoding="utf-8")
    path.write_bytes(pretty)


def export_lanelet2(
    graph: Graph,
    path: str | Path,
    *,
    origin_lat: float,
    origin_lon: float,
    generator: str = "roadgraph_builder",
    speed_limit_tagging: str = "lanelet-attr",
    lane_markings: dict | None = None,
) -> None:
    """Write OSM XML with centerlines, optional lane boundary ways, and lanelet relations.

    Local ``(x, y)`` meters are converted with the same tangent-plane convention as
    :func:`roadgraph_builder.utils.geo.meters_to_lonlat`.

    For each edge that has **both** left and right boundary ways (≥2 vertices each),
    adds a ``<relation>`` with ``type=lanelet`` and members ``role=left`` / ``role=right``.
    If a centerline way exists for the same edge, it is linked with ``role=centerline``
    (supported by common Lanelet2 tooling).

    ``attributes.hd.semantic_rules`` (list of dicts) adds ``speed_limit`` on the
    lanelet and optional ``type=regulatory_element`` relations for kinds such as
    ``traffic_light`` or ``stop_line``.

    Args:
        speed_limit_tagging: ``"lanelet-attr"`` (default, 0.5.0 behavior — speed_limit
            as a tag on the lanelet relation) or ``"regulatory-element"`` (Lanelet2 spec
            style — emits a separate ``type=regulatory_element, subtype=speed_limit``
            relation and omits the inline tag).
        lane_markings: Optional lane_markings.json dict.  When supplied, boundary ways
            get a ``subtype`` tag of ``solid`` or ``dashed`` based on intensity_median
            and point density heuristic.  Without this, all boundary ways get
            ``subtype=solid`` (0.5.0 behavior).
    """
    path = Path(path)
    root = ET.Element("osm", version="0.6", generator=generator)

    next_id = 1
    node_children: list[ET.Element] = []
    way_children: list[ET.Element] = []
    relation_children: list[ET.Element] = []

    def new_node(lat: float, lon: float, tags: dict[str, str] | None = None) -> int:
        nonlocal next_id
        nid = next_id
        next_id += 1
        n_el = ET.Element("node", id=str(nid), lat=_fmt_lonlat(lat), lon=_fmt_lonlat(lon))
        if tags:
            for k, v in tags.items():
                ET.SubElement(n_el, "tag", k=k, v=v)
        node_children.append(n_el)
        return nid

    def new_way(nds: list[int], tags: list[tuple[str, str]]) -> int:
        nonlocal next_id
        w_id = next_id
        next_id += 1
        w_el = ET.Element("way", id=str(w_id))
        for nid in nds:
            ET.SubElement(w_el, "nd", ref=str(nid))
        for k, v in tags:
            ET.SubElement(w_el, "tag", k=k, v=v)
        way_children.append(w_el)
        return w_id

    def new_relation(members: list[tuple[str, int, str]], tags: list[tuple[str, str]]) -> int:
        nonlocal next_id
        r_id = next_id
        next_id += 1
        r_el = ET.Element("relation", id=str(r_id))
        for mtype, ref, role in members:
            ET.SubElement(r_el, "member", type=mtype, ref=str(ref), role=role)
        for k, v in tags:
            ET.SubElement(r_el, "tag", k=k, v=v)
        relation_children.append(r_el)
        return r_id

    for n in graph.nodes:
        lon, lat = meters_to_lonlat(float(n.position[0]), float(n.position[1]), origin_lat, origin_lon)
        n_tags: dict[str, str] = {
            "roadgraph": "graph_node",
            "roadgraph:node_id": str(n.id),
        }
        # 3D: emit ele tag when elevation data is available on the node.
        _elev = None
        n_attrs = n.attributes if isinstance(n.attributes, dict) else {}
        # Check direct attribute first (from 3D build), then hd block.
        _raw_elev = n_attrs.get("elevation_m")
        if _raw_elev is None:
            _hd_n = n_attrs.get("hd")
            if isinstance(_hd_n, dict):
                _raw_elev = _hd_n.get("elevation_m")
        if _raw_elev is not None:
            try:
                _elev = float(_raw_elev)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass
        if _elev is not None:
            n_tags["ele"] = f"{_elev:.3f}"
        new_node(lat, lon, n_tags)

    # Track edge_id → lanelet relation id so the post-pass can wire junction
    # connectivity between consecutive lanelets.
    lanelet_id_by_edge: dict[str, int] = {}

    for e in graph.edges:
        center_nd: list[int] = []
        for x, y in e.polyline:
            lon, lat = meters_to_lonlat(float(x), float(y), origin_lat, origin_lon)
            center_nd.append(new_node(lat, lon, None))

        center_way_id: int | None = None
        if len(center_nd) >= 2:
            center_way_id = new_way(
                center_nd,
                [
                    ("roadgraph", "centerline"),
                    ("roadgraph:edge_id", str(e.id)),
                    ("type", "line_thin"),
                    ("subtype", "solid"),
                ],
            )

        left_way_id: int | None = None
        right_way_id: int | None = None

        hd = e.attributes.get("hd")
        if isinstance(hd, dict):
            lb = hd.get("lane_boundaries")
            if isinstance(lb, dict):
                # Determine boundary subtype from lane_markings heuristic (δ).
                lm_candidates = None
                if lane_markings is not None:
                    lm_candidates = [
                        c for c in lane_markings.get("candidates", [])
                        if isinstance(c, dict) and c.get("edge_id") == e.id
                    ]
                boundary_subtype = _lane_marking_subtype(lm_candidates)
                for side in ("left", "right"):
                    raw = lb.get(side)
                    if not isinstance(raw, list) or len(raw) < 2:
                        continue
                    nds: list[int] = []
                    for p in raw:
                        if not isinstance(p, dict):
                            continue
                        lon, lat = meters_to_lonlat(float(p["x"]), float(p["y"]), origin_lat, origin_lon)
                        nds.append(new_node(lat, lon, None))
                    if len(nds) < 2:
                        continue
                    wid = new_way(
                        nds,
                        [
                            ("roadgraph", "lane_boundary"),
                            ("roadgraph:edge_id", str(e.id)),
                            ("roadgraph:side", side),
                            ("type", "line_thin"),
                            ("subtype", boundary_subtype),
                        ],
                    )
                    if side == "left":
                        left_way_id = wid
                    else:
                        right_way_id = wid

        if left_way_id is not None and right_way_id is not None:
            members: list[tuple[str, int, str]] = [
                ("way", left_way_id, "left"),
                ("way", right_way_id, "right"),
            ]
            if center_way_id is not None:
                members.append(("way", center_way_id, "centerline"))
            hd_use = hd if isinstance(hd, dict) else {}
            lanelet_tags: list[tuple[str, str]] = [
                ("type", "lanelet"),
                ("subtype", "road"),
                ("location", "urban"),
                ("roadgraph:edge_id", str(e.id)),
            ]
            # δ: speed_limit tagging mode.
            if speed_limit_tagging == "regulatory-element":
                # Emit a separate speed_limit regulatory_element; omit inline tag.
                semantic_rules = hd_use.get("semantic_rules")
                if isinstance(semantic_rules, list):
                    speeds = []
                    for r in semantic_rules:
                        if isinstance(r, dict) and r.get("kind") == "speed_limit" and "value_kmh" in r:
                            try:
                                speeds.append(int(float(r["value_kmh"])))
                            except (TypeError, ValueError):
                                pass
                    ll_rid = new_relation(members, lanelet_tags)
                    lanelet_id_by_edge[e.id] = ll_rid
                    if speeds:
                        _build_speed_limit_regulatory(min(speeds), ll_rid, new_relation)
                    _emit_regulatory_elements_for_lanelet(semantic_rules, ll_rid, new_relation)
                else:
                    ll_rid = new_relation(members, lanelet_tags)
                    lanelet_id_by_edge[e.id] = ll_rid
            else:
                # Default (lanelet-attr): speed_limit as inline tag (0.5.0 behavior).
                lanelet_tags.extend(_lanelet_tags_from_semantic_rules(hd_use.get("semantic_rules")))
                ll_rid = new_relation(members, lanelet_tags)
                lanelet_id_by_edge[e.id] = ll_rid
                _emit_regulatory_elements_for_lanelet(hd_use.get("semantic_rules"), ll_rid, new_relation)

    # Lane connectivity: for every graph node where ≥2 lanelets meet, emit one
    # `type=regulatory_element subtype=lane_connection` relation listing each
    # incident lanelet as a member. The member role records whether the
    # lanelet's canonical start or end node anchors the junction, so a
    # downstream consumer can distinguish incoming from outgoing.
    if lanelet_id_by_edge:
        node_lanelets: dict[str, list[tuple[int, str]]] = {}
        for e in graph.edges:
            rid = lanelet_id_by_edge.get(e.id)
            if rid is None:
                continue
            node_lanelets.setdefault(e.start_node_id, []).append((rid, "from_start"))
            if e.end_node_id != e.start_node_id:
                node_lanelets.setdefault(e.end_node_id, []).append((rid, "from_end"))
        node_attrs = {n.id: dict(n.attributes) for n in graph.nodes}
        for node_id, entries in node_lanelets.items():
            if len(entries) < 2:
                continue
            members = [("relation", rid, role) for rid, role in entries]
            conn_tags = [
                ("type", "regulatory_element"),
                ("subtype", "lane_connection"),
                ("roadgraph", "lane_connection"),
                ("roadgraph:junction_node_id", str(node_id)),
            ]
            jt = node_attrs.get(node_id, {}).get("junction_type")
            if isinstance(jt, str):
                conn_tags.append(("roadgraph:junction_type", jt))
            jh = node_attrs.get(node_id, {}).get("junction_hint")
            if isinstance(jh, str):
                conn_tags.append(("roadgraph:junction_hint", jh))
            new_relation(members, conn_tags)

    for c in node_children:
        root.append(c)
    for c in way_children:
        root.append(c)
    for c in relation_children:
        root.append(c)

    xml_bytes = ET.tostring(root, encoding="utf-8")
    dom = minidom.parseString(xml_bytes)
    pretty = dom.toprettyxml(indent="  ", encoding="utf-8")
    path.write_bytes(pretty)
