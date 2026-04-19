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
        new_node(
            lat,
            lon,
            {
                "roadgraph": "graph_node",
                "roadgraph:node_id": str(n.id),
            },
        )

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
                            ("subtype", "solid"),
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
