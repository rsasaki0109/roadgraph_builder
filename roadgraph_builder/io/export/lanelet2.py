"""Export a road graph to OSM XML 0.6 (WGS84) for Lanelet2 / JOSM-style tooling.

This writes **nodes**, **ways**, then **relations**. When an edge has both
``hd.lane_boundaries`` polylines, it also emits a Lanelet2-style **lanelet**
relation (``type=lanelet``) with ``left`` / ``right`` way members.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.utils.geo import meters_to_lonlat


def _et_to_pretty_bytes(root: ET.Element) -> bytes:
    """Serialize an ElementTree to pretty-printed UTF-8 bytes.

    Produces output byte-identical to ``minidom.toprettyxml(indent='  ',
    encoding='utf-8')`` without the minidom round-trip parse (which allocated
    ~900 KB of DOM objects for a Paris-scale graph).  The format rules are:
    - XML declaration on line 1.
    - Self-closing tags use ``/>`` (no space before slash, matching minidom).
    - Text-only elements are inlined on one line.
    - Child-bearing elements open, recurse indented, then close.
    """
    chunks: list[bytes] = [b'<?xml version="1.0" encoding="utf-8"?>\n']

    def _attrs(el: ET.Element) -> bytes:
        if not el.attrib:
            return b""
        return b" " + b" ".join(
            f'{k}="{v}"'.encode("utf-8") for k, v in el.attrib.items()
        )

    def _write(el: ET.Element, depth: int) -> None:
        prefix = b"  " * depth
        tag = el.tag.encode("utf-8")
        attrs = _attrs(el)
        children = list(el)
        text = (el.text or "").strip()

        if not children and not text:
            chunks.append(prefix + b"<" + tag + attrs + b"/>\n")
        elif not children:
            chunks.append(
                prefix + b"<" + tag + attrs + b">" + text.encode("utf-8") + b"</" + tag + b">\n"
            )
        else:
            chunks.append(prefix + b"<" + tag + attrs + b">\n")
            for child in children:
                _write(child, depth + 1)
            chunks.append(prefix + b"</" + tag + b">\n")

    _write(root, 0)
    return b"".join(chunks)

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


def _autoware_lanelet_tags_from_attributes(attrs: dict) -> list[tuple[str, str]]:
    """Derive Autoware-spec lanelet tags from road-graph edge attributes.

    Autoware expects every vehicle-accessible lanelet to carry at minimum:

    - ``one_way`` (``yes`` / ``no``), otherwise a warning / routing ambiguity
    - ``participant:vehicle`` so the autoware_planning stack knows the lanelet
      is for cars (pedestrian lanelets get ``participant:vehicle=no``)
    - ``speed_limit`` with a unit so the behaviour planner has a cap

    This helper looks at OSM-derived attributes we stamp via
    ``scripts/refresh_docs_assets.py`` (``osm_oneway``, ``osm_maxspeed``,
    ``osm_lanes``) plus the ``hd.semantic_rules`` speed-limit fallback.
    Returns a list of (key, value) tuples to extend the lanelet tag list.
    """
    if not isinstance(attrs, dict):
        return []
    extra: list[tuple[str, str]] = []

    # one_way from OSM tag values. OSM convention:
    #   yes / true / 1 → one-way forward
    #   -1 / reverse    → one-way reverse (treat as one_way=yes; direction
    #                     handling is up to the routing consumer)
    #   no / false / 0 → bidirectional
    #   missing        → default no (bidirectional) to avoid silent routing
    one_way = "no"
    raw = attrs.get("osm_oneway")
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in {"yes", "true", "1", "-1", "reverse"}:
            one_way = "yes"
        elif token in {"no", "false", "0"}:
            one_way = "no"
    extra.append(("one_way", one_way))
    extra.append(("participant:vehicle", "yes"))

    # speed_limit from the OSM ``maxspeed`` tag. Autoware reads the unit, so
    # we emit ``<N> km/h`` rather than a bare number. Semantic-rules speed
    # limits are handled separately by ``_lanelet_tags_from_semantic_rules``
    # (which still emits a bare number to preserve 0.5.0 byte-for-byte
    # behaviour) and by the regulatory-element tagging mode, so we stay out
    # of that path to avoid duplicating or colliding with either.
    maxspeed = attrs.get("osm_maxspeed")
    if isinstance(maxspeed, str):
        try:
            value = float(maxspeed.strip().split()[0])
            if value > 0:
                extra.append(("speed_limit", f"{int(value)} km/h"))
        except (TypeError, ValueError):
            pass

    # OSM name helps humans read the map in RViz; purely informational.
    name = attrs.get("osm_name")
    if isinstance(name, str) and name:
        extra.append(("name", name))

    # OSM width (metres) — emitted for the lanelet as an advisory "width"
    # attribute (Autoware reads this when available; it does not replace the
    # per-lane boundaries that carry the real paint lines).
    width_raw = attrs.get("osm_width_m")
    if isinstance(width_raw, (int, float)) and float(width_raw) > 0:
        extra.append(("width", f"{float(width_raw):.2f} m"))

    return extra


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
    lane_markings: dict | None = None,
) -> None:
    """Write per-lane Lanelet2 OSM XML using ``attributes.hd.lanes`` inferred by lane_inference.

    For edges that have ``attributes.hd.lane_count`` and ``attributes.hd.lanes``, this
    emits one lanelet relation per lane (with ``roadgraph:lane_index`` tag). Edges without
    ``hd.lanes`` fall back to the standard single-lanelet-per-edge output identical to
    :func:`export_lanelet2`.

    Adjacent lanelets on the same edge are linked with a ``type=regulatory_element,
    subtype=lane_change`` relation (one per pair). When ``lane_markings`` is provided,
    the boundary subtype (solid/dashed) between adjacent lanes is used to set a
    ``sign`` tag on the relation: ``sign=solid`` for solid boundaries (prohibited) and
    ``sign=dashed`` for dashed boundaries (allowed). Without ``lane_markings`` the sign
    defaults to ``sign=dashed`` (A3 — FOLLOWUP: per-boundary sign would require
    per-lane-pair boundary classification, currently defaulted).
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

    # Graph-node export (same as standard). Emit an ``ele`` tag when the
    # node carries elevation data, either directly via ``elevation_m`` (3D
    # build / refresh elevation stamp) or inside the ``hd`` block.
    for n in graph.nodes:
        lon, lat = meters_to_lonlat(
            float(n.position[0]), float(n.position[1]), origin_lat, origin_lon
        )
        tags: dict[str, str] = {
            "roadgraph": "graph_node",
            "roadgraph:node_id": str(n.id),
        }
        n_attrs = n.attributes if isinstance(n.attributes, dict) else {}
        raw_elev = n_attrs.get("elevation_m")
        if raw_elev is None:
            hd_n = n_attrs.get("hd")
            if isinstance(hd_n, dict):
                raw_elev = hd_n.get("elevation_m")
        if raw_elev is not None:
            try:
                tags["ele"] = f"{float(raw_elev):.2f}"
            except (TypeError, ValueError):
                pass
        new_node(lat, lon, tags)

    from roadgraph_builder.hd.boundaries import centerline_lane_boundaries

    # Track the "first" lanelet id we emit per edge so we can attach
    # regulatory_element relations (traffic_light from camera / OSM semantic
    # rules, stop lines, etc.) against a lanelet the way Autoware expects.
    lanelet_id_by_edge: dict[str, int] = {}

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
            n_lanes = len([l for l in lanes_data if isinstance(l, dict)])
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
                # Boundary subtype semantics for Autoware:
                #   - Outermost boundaries of the road envelope → solid (no
                #     lane change off the road).
                #   - Interior boundaries between adjacent lanes → dashed
                #     (lane change permitted) unless lane_markings explicitly
                #     said the paint between them is solid.
                # The lane_markings override is best-effort: if any candidate
                # for this edge classifies the markings as "solid" we treat
                # all interior boundaries as solid for now.
                interior_subtype = "dashed"
                if lane_markings is not None:
                    lm_for_edge = [
                        c for c in lane_markings.get("candidates", []) or []
                        if isinstance(c, dict) and c.get("edge_id") == e.id
                    ]
                    if _lane_marking_subtype(lm_for_edge) == "solid":
                        interior_subtype = "solid"
                left_subtype = (
                    "solid" if (lane_idx == 0 or n_lanes <= 1) else interior_subtype
                )
                right_subtype = (
                    "solid"
                    if (lane_idx >= n_lanes - 1 or n_lanes <= 1)
                    else interior_subtype
                )
                lw_id = new_way(left_nds, [
                    ("roadgraph", "lane_boundary"),
                    ("roadgraph:edge_id", str(e.id)),
                    ("roadgraph:lane_index", str(lane_idx)),
                    ("roadgraph:side", "left"),
                    ("type", "line_thin"),
                    ("subtype", left_subtype),
                ])
                rw_id = new_way(right_nds, [
                    ("roadgraph", "lane_boundary"),
                    ("roadgraph:edge_id", str(e.id)),
                    ("roadgraph:lane_index", str(lane_idx)),
                    ("roadgraph:side", "right"),
                    ("type", "line_thin"),
                    ("subtype", right_subtype),
                ])
                lanelet_tags: list[tuple[str, str]] = [
                    ("type", "lanelet"),
                    ("subtype", "road"),
                    ("location", "urban"),
                    ("roadgraph:edge_id", str(e.id)),
                    ("roadgraph:lane_index", str(lane_idx)),
                ]
                lanelet_tags.extend(_autoware_lanelet_tags_from_attributes(e.attributes))
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
                lanelet_id_by_edge.setdefault(str(e.id), ll_id)

            # Emit lane_change relations for adjacent lanes (A3).
            # Determine sign from lane_markings boundary subtype if available.
            # When lane_markings is not provided, default to "dashed" (permitted).
            if lane_markings is None:
                sign = "dashed"
            else:
                lm_candidates_for_edge = [
                    c for c in lane_markings.get("candidates", [])
                    if isinstance(c, dict) and c.get("edge_id") == e.id
                ]
                sign = "solid" if _lane_marking_subtype(lm_candidates_for_edge) == "solid" else "dashed"
            for i in range(len(edge_lanelet_ids) - 1):
                new_relation(
                    [
                        ("relation", edge_lanelet_ids[i], "lanelet"),
                        ("relation", edge_lanelet_ids[i + 1], "lanelet"),
                    ],
                    [
                        ("type", "regulatory_element"),
                        ("subtype", "lane_change"),
                        ("sign", sign),
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
                ll_tags.extend(_autoware_lanelet_tags_from_attributes(e.attributes))
                ll_tags.extend(_lanelet_tags_from_semantic_rules(hd_use.get("semantic_rules")))
                ll_id = new_relation(members, ll_tags)
                lanelet_id_by_edge.setdefault(str(e.id), ll_id)

    # Regulatory elements from semantic_rules / camera detections. Autoware
    # treats traffic_lights and stop_lines as separate relations that a
    # lanelet "refers" to, so we emit them against the first lanelet per
    # edge (for multi-lane edges, lane 0). Only rules with enough position
    # data (`world_xy_m`) get a positioned node; others are skipped silently
    # — the caller can always fall back to camera_detections JSON wiring on
    # `export_lanelet2` for the old path.
    for e in graph.edges:
        hd_edge = e.attributes.get("hd") if isinstance(e.attributes.get("hd"), dict) else {}
        rules = hd_edge.get("semantic_rules") if isinstance(hd_edge, dict) else None
        if not isinstance(rules, list):
            continue
        ll_ref = lanelet_id_by_edge.get(str(e.id))
        if ll_ref is None:
            continue
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            kind = rule.get("kind")
            if kind == "traffic_light":
                _build_traffic_light_regulatory(
                    rule, ll_ref, new_node, new_relation, origin_lat, origin_lon
                )
            elif kind == "stop_line":
                _build_stop_line_way(
                    rule, new_node, new_way, origin_lat, origin_lon
                )

    # Lane connectivity: for every graph node where ≥2 lanelets meet, emit a
    # `type=regulatory_element, subtype=lane_connection` relation listing
    # each incident lanelet (member role records whether its canonical start
    # or end node anchors the junction). Autoware's planner consults this to
    # treat consecutive lanelets across a junction as a single routable
    # path. Mirrors the equivalent block in `export_lanelet2`.
    if lanelet_id_by_edge:
        node_lanelets: dict[str, list[tuple[int, str]]] = {}
        for e in graph.edges:
            rid = lanelet_id_by_edge.get(str(e.id))
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
            conn_tags: list[tuple[str, str]] = [
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

    path.write_bytes(_et_to_pretty_bytes(root))


def _build_stop_line_way(
    stop_line_detection: dict,
    new_node_fn,
    new_way_fn,
    origin_lat: float,
    origin_lon: float,
) -> int | None:
    """Build a stop_line way from a camera detection dict.

    Returns the new way id, or None if the detection lacks enough position data.
    The stop line is represented as a ``type=line_thin, subtype=solid`` way.
    """
    from roadgraph_builder.utils.geo import meters_to_lonlat as _mtll

    # Expect either a 'polyline_m' list of [x, y] points or a 'world_xy_m' single point.
    polyline = stop_line_detection.get("polyline_m")
    if polyline and isinstance(polyline, list) and len(polyline) >= 2:
        pts: list[tuple[float, float]] = []
        for pt in polyline:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                pts.append((float(pt[0]), float(pt[1])))
        if len(pts) < 2:
            return None
    else:
        # Fallback: single world_xy_m point is not enough for a way (need 2+).
        return None

    nds: list[int] = []
    for x, y in pts:
        lon, lat = _mtll(x, y, origin_lat, origin_lon)
        nds.append(new_node_fn(lat, lon, None))

    return new_way_fn(
        nds,
        [
            ("type", "line_thin"),
            ("subtype", "solid"),
            ("roadgraph:source", "camera_detections"),
            ("roadgraph:kind", "stop_line"),
        ],
    )


def export_lanelet2(
    graph: Graph,
    path: str | Path,
    *,
    origin_lat: float,
    origin_lon: float,
    generator: str = "roadgraph_builder",
    speed_limit_tagging: str = "lanelet-attr",
    lane_markings: dict | None = None,
    camera_detections: dict | None = None,
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
        camera_detections: Optional camera_detections.json dict (``{observations: [...]}``)
            from ``apply-camera`` or ``project-camera``. When supplied, detections with
            ``kind=traffic_light`` produce a ``subtype=traffic_light`` regulatory_element
            relation and detections with ``kind=stop_line`` produce a ``type=line_thin,
            subtype=solid`` way. These are emitted after all lanelet relations. Without
            this argument, output is byte-identical to the v0.6.0 δ baseline.
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
            lanelet_tags.extend(_autoware_lanelet_tags_from_attributes(e.attributes))
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

    # A1: camera_detections wiring — emit regulatory_element relations for
    # traffic_light detections and stop_line ways from the detections JSON.
    if camera_detections is not None:
        observations = camera_detections.get("observations", [])
        if not isinstance(observations, list):
            observations = []
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            kind = obs.get("kind")
            if kind == "traffic_light":
                # Find the associated lanelet (by edge_id if present).
                edge_id = obs.get("edge_id")
                lanelet_rid: int | None = None
                if edge_id is not None:
                    lanelet_rid = lanelet_id_by_edge.get(str(edge_id))
                if lanelet_rid is None and lanelet_id_by_edge:
                    # Fall back to using any available lanelet.
                    lanelet_rid = next(iter(lanelet_id_by_edge.values()))
                if lanelet_rid is not None:
                    _build_traffic_light_regulatory(
                        obs,
                        lanelet_rid,
                        new_node,
                        new_relation,
                        origin_lat,
                        origin_lon,
                    )
            elif kind == "stop_line":
                _build_stop_line_way(
                    obs,
                    new_node,
                    new_way,
                    origin_lat,
                    origin_lon,
                )

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

    path.write_bytes(_et_to_pretty_bytes(root))
