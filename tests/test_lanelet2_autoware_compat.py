from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from roadgraph_builder.io.export.lanelet2 import sanitize_lanelet2_for_autoware


def _tags(el: ET.Element) -> dict[str, str]:
    return {t.attrib["k"]: t.attrib["v"] for t in el.findall("tag")}


def test_sanitize_lanelet2_for_autoware_strips_loader_blockers(tmp_path: Path):
    src = tmp_path / "rich.osm"
    dst = tmp_path / "compat.osm"
    src.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<osm version="0.6">
  <MetaInfo format_version="1" map_version="1" origin_lat="35.0" origin_lon="139.0"/>
  <node id="1" lat="0" lon="0">
    <tag k="type" v="traffic_light"/>
    <tag k="roadgraph:node_id" v="n0"/>
  </node>
  <node id="2" lat="0" lon="0.0001">
    <tag k="ele" v="12.34"/>
  </node>
  <way id="10">
    <nd ref="1"/>
    <nd ref="2"/>
    <tag k="type" v="line_thin"/>
    <tag k="subtype" v="solid"/>
    <tag k="roadgraph:edge_id" v="e0"/>
  </way>
  <relation id="20">
    <member type="way" ref="10" role="left"/>
    <member type="way" ref="10" role="right"/>
    <tag k="type" v="lanelet"/>
    <tag k="subtype" v="road"/>
    <tag k="location" v="urban"/>
    <tag k="roadgraph:edge_id" v="e0"/>
    <tag k="width" v="3.50 m"/>
  </relation>
  <relation id="21">
    <member type="relation" ref="20" role="lanelet"/>
    <tag k="type" v="regulatory_element"/>
    <tag k="subtype" v="lane_change"/>
  </relation>
  <relation id="22">
    <member type="relation" ref="20" role="refers"/>
    <member type="node" ref="1" role="refers"/>
    <tag k="type" v="regulatory_element"/>
    <tag k="subtype" v="traffic_light"/>
  </relation>
</osm>
""",
        encoding="utf-8",
    )

    stats = sanitize_lanelet2_for_autoware(
        src,
        dst,
        fill_missing_ele=4.2,
        default_turn_direction="straight",
    )

    assert stats == {
        "removed_regulatory_relations": 1,
        "kept_traffic_light_regulatory_relations": 1,
        "generated_traffic_light_nodes": 2,
        "generated_traffic_light_ways": 1,
        "added_traffic_light_height_tags": 1,
        "added_traffic_light_id_tags": 1,
        "added_traffic_light_bulb_members": 1,
        "removed_roadgraph_tags": 3,
        "removed_width_tags": 1,
        "removed_point_traffic_light_tags": 1,
        "filled_missing_ele": 1,
        "added_turn_direction": 1,
        "wrote_map_projector_info": 0,
    }
    root = ET.parse(dst).getroot()
    all_tags = [tag for elem in root for tag in elem.findall("tag")]
    assert not any(t.attrib["k"] == "roadgraph" for t in all_tags)
    assert not any(t.attrib["k"].startswith("roadgraph:") for t in all_tags)
    assert not any(t.attrib["k"] == "width" for t in all_tags)
    assert not any(t.attrib == {"k": "type", "v": "traffic_light"} for t in all_tags)

    relations = root.findall("relation")
    assert len(relations) == 2
    lanelet = next(r for r in relations if _tags(r).get("type") == "lanelet")
    traffic_light = next(
        r for r in relations if _tags(r).get("subtype") == "traffic_light"
    )
    lanelet_tags = _tags(lanelet)
    assert lanelet_tags["type"] == "lanelet"
    assert lanelet_tags["turn_direction"] == "straight"
    assert any(
        m.attrib == {"type": "relation", "ref": "22", "role": "regulatory_element"}
        for m in lanelet.findall("member")
    )
    assert any(
        m.attrib.get("type") == "way" and m.attrib.get("role") == "refers"
        for m in traffic_light.findall("member")
    )
    assert any(
        m.attrib.get("type") == "way" and m.attrib.get("role") == "light_bulbs"
        for m in traffic_light.findall("member")
    )
    signal_way_id = next(
        m.attrib["ref"]
        for m in traffic_light.findall("member")
        if m.attrib.get("role") == "refers"
    )
    signal_way = next(w for w in root.findall("way") if w.attrib.get("id") == signal_way_id)
    assert _tags(signal_way)["height"] == "5.00"
    assert _tags(signal_way)["traffic_light_id"] == "22"

    node_tags = {n.attrib["id"]: _tags(n) for n in root.findall("node")}
    assert node_tags["1"]["ele"] == "12.34"
    assert node_tags["2"]["ele"] == "12.34"


def test_sanitize_lanelet2_for_autoware_can_leave_placeholders_off(tmp_path: Path):
    src = tmp_path / "rich.osm"
    dst = tmp_path / "compat.osm"
    src.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<osm version="0.6">
  <node id="1" lat="0" lon="0"/>
  <relation id="20">
    <tag k="type" v="lanelet"/>
    <tag k="subtype" v="road"/>
    <tag k="location" v="urban"/>
  </relation>
</osm>
""",
        encoding="utf-8",
    )

    stats = sanitize_lanelet2_for_autoware(
        src,
        dst,
        fill_missing_ele=None,
        default_turn_direction=None,
    )

    assert stats["filled_missing_ele"] == 0
    assert stats["added_turn_direction"] == 0
    root = ET.parse(dst).getroot()
    assert "ele" not in _tags(root.find("node"))  # type: ignore[arg-type]
    assert "turn_direction" not in _tags(root.find("relation"))  # type: ignore[arg-type]


def test_sanitize_lanelet2_for_autoware_infers_turn_direction(tmp_path: Path):
    src = tmp_path / "rich.osm"
    dst = tmp_path / "compat.osm"
    src.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<osm version="0.6">
  <node id="1" lat="0" lon="0"/>
  <node id="2" lat="0" lon="0.001"/>
  <node id="3" lat="0.001" lon="0.001"/>
  <way id="10">
    <nd ref="1"/>
    <nd ref="2"/>
    <nd ref="3"/>
  </way>
  <relation id="20">
    <member type="way" ref="10" role="centerline"/>
    <tag k="type" v="lanelet"/>
    <tag k="subtype" v="road"/>
    <tag k="location" v="urban"/>
  </relation>
</osm>
""",
        encoding="utf-8",
    )

    stats = sanitize_lanelet2_for_autoware(
        src,
        dst,
        fill_missing_ele=None,
        default_turn_direction="infer",
    )

    assert stats["added_turn_direction"] == 1
    relation = ET.parse(dst).getroot().find("relation")
    assert relation is not None
    assert _tags(relation)["turn_direction"] == "left"


def test_sanitize_lanelet2_for_autoware_uses_nearest_existing_ele(tmp_path: Path):
    src = tmp_path / "rich.osm"
    dst = tmp_path / "compat.osm"
    src.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<osm version="0.6">
  <node id="1" lat="0" lon="0">
    <tag k="ele" v="42.0"/>
  </node>
  <node id="2" lat="0" lon="0.00001"/>
</osm>
""",
        encoding="utf-8",
    )

    stats = sanitize_lanelet2_for_autoware(src, dst, fill_missing_ele=0.0)

    assert stats["filled_missing_ele"] == 1
    node_tags = {n.attrib["id"]: _tags(n) for n in ET.parse(dst).getroot().findall("node")}
    assert node_tags["2"]["ele"] == "42.00"


def test_sanitize_lanelet2_for_autoware_writes_map_projector_info(tmp_path: Path):
    src = tmp_path / "rich.osm"
    dst = tmp_path / "compat.osm"
    projector = tmp_path / "map_projector_info.yaml"
    src.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<osm version="0.6">
  <MetaInfo format_version="1" map_version="1" origin_lat="37.8" origin_lon="-122.415"/>
</osm>
""",
        encoding="utf-8",
    )

    stats = sanitize_lanelet2_for_autoware(
        src,
        dst,
        map_projector_info_yaml=projector,
    )

    assert stats["wrote_map_projector_info"] == 1
    assert projector.read_text(encoding="utf-8") == (
        "projector_type: LocalCartesian\n"
        "vertical_datum: WGS84\n"
        "map_origin:\n"
        "  latitude: 37.8\n"
        "  longitude: -122.415\n"
    )
