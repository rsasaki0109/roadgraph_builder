"""Export a road graph to OSM XML 0.6 (WGS84) for Lanelet2 / JOSM-style tooling.

This writes **nodes**, **ways**, then **relations**. When an edge has both
``hd.lane_boundaries`` polylines, it also emits a Lanelet2-style **lanelet**
relation (``type=lanelet``) with ``left`` / ``right`` way members.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import math
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


def sanitize_lanelet2_for_autoware(
    input_path: str | Path,
    output_path: str | Path,
    *,
    fill_missing_ele: float | None = 0.0,
    default_turn_direction: str | None = "infer",
    map_projector_info_yaml: str | Path | None = None,
    traffic_light_height_m: float = 5.0,
) -> dict[str, int]:
    """Write a conservative Autoware loader-smoke variant of a Lanelet2 OSM.

    Roadgraph's rich docs maps intentionally include experimental regulatory
    relations such as ``lane_change`` and ``lane_connection`` plus diagnostic
    ``roadgraph:*`` tags. Stock Lanelet2 readers reject those custom regulatory
    element subtypes, while Autoware's validator expects every point to have
    ``ele`` and intersecting lanelets to carry ``turn_direction``. This helper
    keeps the lanelet geometry and Autoware lanelet tags, but strips regulatory
    relations and Roadgraph-only tags so the map can be used for loader smoke
    tests. Missing ``ele`` tags are filled from the nearest existing elevation
    point when possible, falling back to ``fill_missing_ele``. When
    ``default_turn_direction="infer"``, lanelet geometry is used to infer
    ``left`` / ``right`` / ``straight``. This is not a substitute for
    survey-grade semantic map authoring.
    """
    in_path = Path(input_path)
    out_path = Path(output_path)
    tree = ET.parse(in_path)
    root = tree.getroot()

    stats = {
        "removed_regulatory_relations": 0,
        "kept_traffic_light_regulatory_relations": 0,
        "generated_traffic_light_nodes": 0,
        "generated_traffic_light_ways": 0,
        "added_traffic_light_height_tags": 0,
        "added_traffic_light_id_tags": 0,
        "added_traffic_light_bulb_members": 0,
        "removed_roadgraph_tags": 0,
        "removed_width_tags": 0,
        "removed_point_traffic_light_tags": 0,
        "filled_missing_ele": 0,
        "added_turn_direction": 0,
        "wrote_map_projector_info": 0,
    }

    node_lonlat: dict[str, tuple[float, float]] = {}
    raw_ele_points: list[tuple[float, float, float]] = []
    for node in root.findall("node"):
        try:
            lat = float(node.attrib["lat"])
            lon = float(node.attrib["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        node_lonlat[str(node.attrib.get("id", ""))] = (lat, lon)
        tags = {t.attrib.get("k"): t.attrib.get("v") for t in node.findall("tag")}
        raw_ele = tags.get("ele")
        if raw_ele is not None:
            try:
                raw_ele_points.append((lat, lon, float(raw_ele)))
            except (TypeError, ValueError):
                pass

    ref_lat = (
        sum(lat for lat, _lon in node_lonlat.values()) / len(node_lonlat)
        if node_lonlat
        else 0.0
    )
    ele_points = [
        (*_sanitize_lonlat_xy(lat, lon, ref_lat), ele)
        for lat, lon, ele in raw_ele_points
    ]
    way_node_refs: dict[str, list[str]] = {
        str(way.attrib.get("id", "")): [
            str(nd.attrib.get("ref", "")) for nd in way.findall("nd")
        ]
        for way in root.findall("way")
    }
    relation_by_id: dict[str, ET.Element] = {
        str(rel.attrib.get("id", "")): rel for rel in root.findall("relation")
    }
    lanelet_by_id = {
        rel_id: rel
        for rel_id, rel in relation_by_id.items()
        if _element_tags_for_sanitize(rel).get("type") == "lanelet"
    }

    def nearest_ele(lat: float, lon: float) -> float | None:
        if not ele_points:
            return None
        x, y = _sanitize_lonlat_xy(lat, lon, ref_lat)
        best_d2 = float("inf")
        best_ele: float | None = None
        for ex, ey, ele in ele_points:
            d2 = (x - ex) * (x - ex) + (y - ey) * (y - ey)
            if d2 < best_d2:
                best_d2 = d2
                best_ele = ele
        return best_ele

    next_id = _next_osm_id_for_sanitize(root)

    def new_id() -> int:
        nonlocal next_id
        out = next_id
        next_id += 1
        return out

    for rel in list(root.findall("relation")):
        tags = _element_tags_for_sanitize(rel)
        if tags.get("type") != "regulatory_element":
            continue
        if tags.get("subtype") == "traffic_light":
            converted = _convert_traffic_light_relation_for_sanitize(
                root,
                rel,
                new_id_fn=new_id,
                node_lonlat=node_lonlat,
                way_node_refs=way_node_refs,
                lanelet_by_id=lanelet_by_id,
                nearest_ele=nearest_ele,
                ref_lat=ref_lat,
                traffic_light_height_m=traffic_light_height_m,
            )
            if converted is not None:
                new_nodes, new_ways, height_tags, id_tags, bulb_members = converted
                stats["kept_traffic_light_regulatory_relations"] += 1
                stats["generated_traffic_light_nodes"] += new_nodes
                stats["generated_traffic_light_ways"] += new_ways
                stats["added_traffic_light_height_tags"] += height_tags
                stats["added_traffic_light_id_tags"] += id_tags
                stats["added_traffic_light_bulb_members"] += bulb_members
                continue
        root.remove(rel)
        stats["removed_regulatory_relations"] += 1

    for elem in list(root):
        for tag in list(elem.findall("tag")):
            k = tag.attrib.get("k", "")
            v = tag.attrib.get("v", "")
            if k == "roadgraph" or k.startswith("roadgraph:"):
                elem.remove(tag)
                stats["removed_roadgraph_tags"] += 1
            elif k == "width":
                elem.remove(tag)
                stats["removed_width_tags"] += 1
            elif elem.tag == "node" and k == "type" and v == "traffic_light":
                elem.remove(tag)
                stats["removed_point_traffic_light_tags"] += 1

        if elem.tag == "node" and fill_missing_ele is not None:
            if not any(t.attrib.get("k") == "ele" for t in elem.findall("tag")):
                try:
                    lat = float(elem.attrib["lat"])
                    lon = float(elem.attrib["lon"])
                except (KeyError, TypeError, ValueError):
                    ele = float(fill_missing_ele)
                else:
                    ele = nearest_ele(lat, lon)
                    if ele is None:
                        ele = float(fill_missing_ele)
                ET.SubElement(elem, "tag", k="ele", v=f"{ele:.2f}")
                stats["filled_missing_ele"] += 1
            continue

        if elem.tag != "relation" or default_turn_direction is None:
            continue
        tags = {t.attrib.get("k"): t.attrib.get("v") for t in elem.findall("tag")}
        if tags.get("type") == "lanelet" and "turn_direction" not in tags:
            turn_direction = default_turn_direction
            if default_turn_direction == "infer":
                turn_direction = _infer_lanelet_turn_direction(
                    elem,
                    node_lonlat=node_lonlat,
                    way_node_refs=way_node_refs,
                    ref_lat=ref_lat,
                )
            ET.SubElement(elem, "tag", k="turn_direction", v=turn_direction)
            stats["added_turn_direction"] += 1

    if map_projector_info_yaml is not None:
        _write_map_projector_info_yaml(root, Path(map_projector_info_yaml))
        stats["wrote_map_projector_info"] = 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(_et_to_pretty_bytes(root))
    return stats


def _sanitize_lonlat_xy(lat: float, lon: float, ref_lat: float) -> tuple[float, float]:
    """Small local coordinate helper for sanitizer-only nearest/heading logic."""

    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    return (lon_rad * math.cos(math.radians(ref_lat)), lat_rad)


def _element_tags_for_sanitize(el: ET.Element) -> dict[str, str]:
    return {
        str(t.attrib.get("k", "")): str(t.attrib.get("v", ""))
        for t in el.findall("tag")
        if t.attrib.get("k") is not None
    }


def _next_osm_id_for_sanitize(root: ET.Element) -> int:
    max_id = 0
    for elem in root:
        try:
            max_id = max(max_id, int(elem.attrib.get("id", "0")))
        except (TypeError, ValueError):
            continue
    return max_id + 1


def _convert_traffic_light_relation_for_sanitize(
    root: ET.Element,
    relation: ET.Element,
    *,
    new_id_fn: Callable[[], int],
    node_lonlat: dict[str, tuple[float, float]],
    way_node_refs: dict[str, list[str]],
    lanelet_by_id: dict[str, ET.Element],
    nearest_ele: Callable[[float, float], float | None],
    ref_lat: float,
    traffic_light_height_m: float,
) -> tuple[int, int, int, int, int] | None:
    """Convert Roadgraph point traffic-light relations to Lanelet2 linestring form."""

    lanelet_id: str | None = None
    signal_node_id: str | None = None
    for member in relation.findall("member"):
        if member.attrib.get("type") == "relation" and member.attrib.get("role") in {
            "refers",
            "lanelet",
        }:
            lanelet_id = member.attrib.get("ref")
        elif member.attrib.get("type") == "node" and member.attrib.get("role") == "refers":
            signal_node_id = member.attrib.get("ref")
    if lanelet_id is None or signal_node_id is None:
        return None
    lanelet_rel = lanelet_by_id.get(str(lanelet_id))
    signal_latlon = node_lonlat.get(str(signal_node_id))
    if lanelet_rel is None or signal_latlon is None:
        return None

    line_node_ids: list[int] = []
    signal_lat, signal_lon = signal_latlon
    line_points = _traffic_light_line_points_for_sanitize(
        signal_lat,
        signal_lon,
        lanelet_rel,
        node_lonlat=node_lonlat,
        way_node_refs=way_node_refs,
        ref_lat=ref_lat,
    )
    ele = _existing_node_ele_for_sanitize(root, signal_node_id)
    if ele is None:
        ele = nearest_ele(signal_lat, signal_lon)
    for lat, lon in line_points:
        node_id = new_id_fn()
        n_el = ET.Element("node", id=str(node_id), lat=_fmt_lonlat(lat), lon=_fmt_lonlat(lon))
        if ele is not None:
            ET.SubElement(n_el, "tag", k="ele", v=f"{float(ele):.2f}")
        _insert_child_before_first(root, n_el, {"way", "relation"})
        node_lonlat[str(node_id)] = (lat, lon)
        line_node_ids.append(node_id)

    way_id = new_id_fn()
    w_el = ET.Element("way", id=str(way_id))
    for node_id in line_node_ids:
        ET.SubElement(w_el, "nd", ref=str(node_id))
    ET.SubElement(w_el, "tag", k="height", v=f"{float(traffic_light_height_m):.2f}")
    ET.SubElement(w_el, "tag", k="traffic_light_id", v=str(relation.attrib["id"]))
    _insert_child_before_first(root, w_el, {"relation"})
    way_node_refs[str(way_id)] = [str(node_id) for node_id in line_node_ids]

    for child in list(relation):
        if child.tag == "member":
            relation.remove(child)
    relation.insert(0, ET.Element("member", type="way", ref=str(way_id), role="light_bulbs"))
    relation.insert(0, ET.Element("member", type="way", ref=str(way_id), role="refers"))
    _ensure_lanelet_references_regulatory_element(lanelet_rel, str(relation.attrib["id"]))
    return (len(line_node_ids), 1, 1, 1, 1)


def _traffic_light_line_points_for_sanitize(
    lat: float,
    lon: float,
    lanelet_relation: ET.Element,
    *,
    node_lonlat: dict[str, tuple[float, float]],
    way_node_refs: dict[str, list[str]],
    ref_lat: float,
    half_width_m: float = 0.75,
) -> list[tuple[float, float]]:
    center_points = _lanelet_center_points_for_sanitize(
        lanelet_relation,
        node_lonlat=node_lonlat,
        way_node_refs=way_node_refs,
    )
    hx, hy = 1.0, 0.0
    if len(center_points) >= 2:
        (lat0, lon0), (lat1, lon1) = center_points[-2], center_points[-1]
        hx, hy = _lonlat_vector_m(lat0, lon0, lat1, lon1, ref_lat)
        norm = math.hypot(hx, hy)
        if norm > 1e-9:
            hx, hy = hx / norm, hy / norm
        else:
            hx, hy = 1.0, 0.0
    px, py = -hy, hx
    return [
        _offset_lonlat_m(lat, lon, -px * half_width_m, -py * half_width_m),
        _offset_lonlat_m(lat, lon, px * half_width_m, py * half_width_m),
    ]


def _lonlat_vector_m(
    lat0: float,
    lon0: float,
    lat1: float,
    lon1: float,
    ref_lat: float,
) -> tuple[float, float]:
    meters_per_deg = 111_320.0
    dx = (lon1 - lon0) * meters_per_deg * math.cos(math.radians(ref_lat))
    dy = (lat1 - lat0) * meters_per_deg
    return dx, dy


def _offset_lonlat_m(lat: float, lon: float, dx_m: float, dy_m: float) -> tuple[float, float]:
    meters_per_deg = 111_320.0
    dlat = dy_m / meters_per_deg
    cos_lat = max(math.cos(math.radians(lat)), 1e-9)
    dlon = dx_m / (meters_per_deg * cos_lat)
    return lat + dlat, lon + dlon


def _existing_node_ele_for_sanitize(root: ET.Element, node_id: str | None) -> float | None:
    if node_id is None:
        return None
    for node in root.findall("node"):
        if node.attrib.get("id") != str(node_id):
            continue
        for tag in node.findall("tag"):
            if tag.attrib.get("k") == "ele":
                try:
                    return float(tag.attrib["v"])
                except (TypeError, ValueError):
                    return None
    return None


def _insert_child_before_first(root: ET.Element, child: ET.Element, before_tags: set[str]) -> None:
    for idx, existing in enumerate(list(root)):
        if existing.tag in before_tags:
            root.insert(idx, child)
            return
    root.append(child)


def _ensure_lanelet_references_regulatory_element(lanelet_relation: ET.Element, reg_id: str) -> None:
    for member in lanelet_relation.findall("member"):
        if (
            member.attrib.get("type") == "relation"
            and member.attrib.get("ref") == reg_id
            and member.attrib.get("role") == "regulatory_element"
        ):
            return
    member = ET.Element("member", type="relation", ref=reg_id, role="regulatory_element")
    for idx, child in enumerate(list(lanelet_relation)):
        if child.tag == "tag":
            lanelet_relation.insert(idx, member)
            return
    lanelet_relation.append(member)


def _infer_lanelet_turn_direction(
    relation: ET.Element,
    *,
    node_lonlat: dict[str, tuple[float, float]],
    way_node_refs: dict[str, list[str]],
    ref_lat: float,
    threshold_deg: float = 35.0,
) -> str:
    points = _lanelet_center_points_for_sanitize(
        relation,
        node_lonlat=node_lonlat,
        way_node_refs=way_node_refs,
    )
    if len(points) < 3:
        return "straight"
    start_heading = _segment_heading_deg(points[0], points[1], ref_lat)
    end_heading = _segment_heading_deg(points[-2], points[-1], ref_lat)
    delta = ((end_heading - start_heading + 180.0) % 360.0) - 180.0
    if delta > threshold_deg:
        return "left"
    if delta < -threshold_deg:
        return "right"
    return "straight"


def _segment_heading_deg(
    p0: tuple[float, float],
    p1: tuple[float, float],
    ref_lat: float,
) -> float:
    x0, y0 = _sanitize_lonlat_xy(p0[0], p0[1], ref_lat)
    x1, y1 = _sanitize_lonlat_xy(p1[0], p1[1], ref_lat)
    return math.degrees(math.atan2(y1 - y0, x1 - x0))


def _lanelet_center_points_for_sanitize(
    relation: ET.Element,
    *,
    node_lonlat: dict[str, tuple[float, float]],
    way_node_refs: dict[str, list[str]],
) -> list[tuple[float, float]]:
    members = list(relation.findall("member"))
    for member in members:
        if member.attrib.get("type") == "way" and member.attrib.get("role") == "centerline":
            pts = _way_points_for_sanitize(
                member.attrib.get("ref", ""),
                node_lonlat=node_lonlat,
                way_node_refs=way_node_refs,
            )
            if len(pts) >= 2:
                return pts

    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for member in members:
        if member.attrib.get("type") != "way":
            continue
        role = member.attrib.get("role")
        if role == "left":
            left = _way_points_for_sanitize(
                member.attrib.get("ref", ""),
                node_lonlat=node_lonlat,
                way_node_refs=way_node_refs,
            )
        elif role == "right":
            right = _way_points_for_sanitize(
                member.attrib.get("ref", ""),
                node_lonlat=node_lonlat,
                way_node_refs=way_node_refs,
            )
    if not left or not right:
        return left or right
    n = min(len(left), len(right))
    return [
        ((left[i][0] + right[i][0]) / 2.0, (left[i][1] + right[i][1]) / 2.0)
        for i in range(n)
    ]


def _way_points_for_sanitize(
    way_id: str | None,
    *,
    node_lonlat: dict[str, tuple[float, float]],
    way_node_refs: dict[str, list[str]],
) -> list[tuple[float, float]]:
    refs = way_node_refs.get(str(way_id), [])
    return [node_lonlat[ref] for ref in refs if ref in node_lonlat]


def _write_map_projector_info_yaml(root: ET.Element, output_yaml: Path) -> None:
    meta = root.find("MetaInfo")
    if meta is None:
        raise ValueError("Lanelet2 OSM has no MetaInfo origin for map_projector_info.yaml")
    try:
        lat = float(meta.attrib["origin_lat"])
        lon = float(meta.attrib["origin_lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Lanelet2 OSM MetaInfo is missing origin_lat/origin_lon") from exc

    output_yaml.parent.mkdir(parents=True, exist_ok=True)
    output_yaml.write_text(
        "\n".join(
            [
                "projector_type: LocalCartesian",
                "vertical_datum: WGS84",
                "map_origin:",
                f"  latitude: {_fmt_lonlat(lat)}",
                f"  longitude: {_fmt_lonlat(lon)}",
                "",
            ]
        ),
        encoding="utf-8",
    )


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
# Autoware MetaInfo (origin / projector hint) — embedded in every Lanelet2 OSM
# ---------------------------------------------------------------------------


def _autoware_meta_info_element(
    origin_lat: float,
    origin_lon: float,
    *,
    generator: str = "roadgraph_builder",
) -> ET.Element:
    """Build the ``<MetaInfo>`` element that anchors the Lanelet2 OSM document.

    Lanelet2's stock reader parses the ``format_version`` / ``map_version``
    attributes; everything else is preserved through the round-trip but
    ignored by the spec parser. We piggy-back the projector origin on the
    same element so an Autoware-style ``map_loader`` (or any custom
    consumer) can recover the WGS84 anchor without a separate
    ``map_projector_info.yaml`` sidecar.

    Field naming follows the Autoware Universe ``map_projector_info`` shape
    (``projector_type``, ``map_origin.latitude`` / ``map_origin.longitude``)
    while keeping each field as a flat attribute so it survives plain XML
    parsers.
    """
    return ET.Element(
        "MetaInfo",
        {
            "format_version": "1",
            "map_version": "1",
            "projector_type": "local",
            "origin_lat": _fmt_lonlat(origin_lat),
            "origin_lon": _fmt_lonlat(origin_lon),
            "generator": generator,
        },
    )


# ---------------------------------------------------------------------------
# Lane connectivity helpers (shared by export_lanelet2 and export_lanelet2_per_lane)
# ---------------------------------------------------------------------------


def _flow_directions_for_edge(edge_attrs: object) -> tuple[bool, bool]:
    """Decide which traffic-flow directions are valid for an edge.

    Returns ``(forward, reverse)`` where ``forward`` means traffic drives in
    the start_node→end_node direction and ``reverse`` means end_node→start_node.
    Mirrors the OSM ``oneway`` mapping used in
    :func:`_autoware_lanelet_tags_from_attributes`; missing or unrecognised tag
    values default to bidirectional so we keep emitting the same connectivity
    we did before the directional refactor.
    """
    if isinstance(edge_attrs, dict):
        raw = edge_attrs.get("osm_oneway")
    else:
        raw = None
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in {"yes", "true", "1"}:
            return True, False
        if token in {"-1", "reverse"}:
            return False, True
        if token in {"no", "false", "0"}:
            return True, True
    return True, True


def _emit_lane_connection_relations(
    graph: Graph,
    lanelet_id_by_edge: dict[object, int],
    new_relation: Callable[[list[tuple[str, int, str]], list[tuple[str, str]]], int],
) -> None:
    """Emit `subtype=lane_connection` regulatory_element relations.

    For every junction node, emits one relation per directed
    (predecessor, successor) lanelet pair. The two members carry roles
    ``predecessor`` (lanelet whose traffic flow exits at the junction) and
    ``successor`` (lanelet whose traffic flow enters the junction), so an
    Autoware-style planner can read consecutive-lanelet connectivity directly
    instead of bundling all incident lanelets without direction.

    Bidirectional edges (``oneway=no`` or missing) contribute both flows;
    one-way edges (``oneway=yes`` / ``-1``) contribute only their valid flow.
    Self-pairs (a lanelet flowing into itself across a junction) are skipped.
    """
    if not lanelet_id_by_edge:
        return

    exits_at: dict[str, list[int]] = {}
    entries_at: dict[str, list[int]] = {}

    def _resolve_rid(edge_id: object) -> int | None:
        rid = lanelet_id_by_edge.get(edge_id)
        if rid is None:
            rid = lanelet_id_by_edge.get(str(edge_id))
        return rid

    for e in graph.edges:
        rid = _resolve_rid(e.id)
        if rid is None:
            continue
        forward, reverse = _flow_directions_for_edge(e.attributes)
        if forward:
            entries_at.setdefault(e.start_node_id, []).append(rid)
            exits_at.setdefault(e.end_node_id, []).append(rid)
        if reverse:
            entries_at.setdefault(e.end_node_id, []).append(rid)
            exits_at.setdefault(e.start_node_id, []).append(rid)

    node_attrs = {n.id: dict(n.attributes) for n in graph.nodes}
    junction_nodes = sorted(
        set(exits_at.keys()) | set(entries_at.keys()), key=str
    )

    for node_id in junction_nodes:
        preds = exits_at.get(node_id, [])
        succs = entries_at.get(node_id, [])
        # Skip nodes where fewer than two distinct lanelets meet — they have
        # nothing to connect, matching the pre-directional behaviour.
        distinct = set(preds) | set(succs)
        if len(distinct) < 2:
            continue

        attrs = node_attrs.get(node_id, {})
        base_tags: list[tuple[str, str]] = [
            ("type", "regulatory_element"),
            ("subtype", "lane_connection"),
            ("roadgraph", "lane_connection"),
            ("roadgraph:junction_node_id", str(node_id)),
        ]
        jt = attrs.get("junction_type")
        if isinstance(jt, str):
            base_tags.append(("roadgraph:junction_type", jt))
        jh = attrs.get("junction_hint")
        if isinstance(jh, str):
            base_tags.append(("roadgraph:junction_hint", jh))

        seen: set[tuple[int, int]] = set()
        for pred_rid in preds:
            for succ_rid in succs:
                if pred_rid == succ_rid:
                    continue
                key = (pred_rid, succ_rid)
                if key in seen:
                    continue
                seen.add(key)
                members = [
                    ("relation", pred_rid, "predecessor"),
                    ("relation", succ_rid, "successor"),
                ]
                new_relation(members, base_tags)


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

    # Lane connectivity: emit one `subtype=lane_connection` regulatory_element
    # relation per directed (predecessor, successor) pair at each junction so
    # Autoware-style planners can read consecutive-lanelet connectivity
    # directly. See `_emit_lane_connection_relations` for the rules.
    _emit_lane_connection_relations(graph, lanelet_id_by_edge, new_relation)

    # Autoware-style projector anchor: lives at the top of the document so the
    # standard MetaInfo parser sees it before scanning nodes/ways/relations.
    root.append(_autoware_meta_info_element(origin_lat, origin_lon, generator=generator))
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

    # Lane connectivity: emit directed (predecessor, successor) pairs per
    # junction node — see `_emit_lane_connection_relations`.
    _emit_lane_connection_relations(graph, lanelet_id_by_edge, new_relation)

    root.append(_autoware_meta_info_element(origin_lat, origin_lon, generator=generator))
    for c in node_children:
        root.append(c)
    for c in way_children:
        root.append(c)
    for c in relation_children:
        root.append(c)

    path.write_bytes(_et_to_pretty_bytes(root))
