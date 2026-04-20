"""Attribution pass-through + shipped-asset license embed.

ODbL / CC-BY-style licenses want the attribution to travel with the file.
``export_map_geojson`` / ``write_route_geojson`` / ``convert-osm-
restrictions`` accept optional ``attribution`` / ``license_name`` /
``license_url`` parameters that get stamped into the FeatureCollection
(or turn_restrictions) properties. These tests cover both the pass-through
code path and the shipped OSM-derived assets under ``docs/assets/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.export.geojson import build_map_geojson, export_map_geojson
from roadgraph_builder.routing.geojson_export import build_route_geojson, write_route_geojson
from roadgraph_builder.routing.shortest_path import shortest_path
from roadgraph_builder.validation import validate_turn_restrictions_document


ROOT = Path(__file__).resolve().parent.parent


def _tiny_graph() -> Graph:
    return Graph(
        nodes=[
            Node(id="n0", position=(0.0, 0.0)),
            Node(id="n1", position=(10.0, 0.0)),
        ],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, 0.0), (10.0, 0.0)],
            )
        ],
    )


def test_build_map_geojson_embeds_attribution():
    doc = build_map_geojson(
        _tiny_graph(),
        np.zeros((0, 2)),
        origin_lat=0.0,
        origin_lon=0.0,
        dataset_name="tiny",
        attribution="© OpenStreetMap contributors",
        license_name="ODbL-1.0",
        license_url="https://opendatacommons.org/licenses/odbl/1-0/",
    )
    props = doc["properties"]
    assert props["attribution"] == "© OpenStreetMap contributors"
    assert props["license"] == "ODbL-1.0"
    assert props["license_url"] == "https://opendatacommons.org/licenses/odbl/1-0/"


def test_build_map_geojson_omits_attribution_when_not_passed():
    """Backward compatibility: existing callers without attribution keep working."""
    doc = build_map_geojson(
        _tiny_graph(),
        np.zeros((0, 2)),
        origin_lat=0.0,
        origin_lon=0.0,
        dataset_name="tiny",
    )
    props = doc["properties"]
    assert "attribution" not in props
    assert "license" not in props
    assert "license_url" not in props


def test_export_map_geojson_writes_attribution(tmp_path: Path):
    out = tmp_path / "tiny.geojson"
    export_map_geojson(
        _tiny_graph(),
        np.zeros((0, 2)),
        out,
        origin_lat=0.0,
        origin_lon=0.0,
        dataset_name="tiny",
        attribution="© OpenStreetMap contributors",
        license_name="ODbL-1.0",
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["properties"]["attribution"] == "© OpenStreetMap contributors"
    assert data["properties"]["license"] == "ODbL-1.0"


def test_build_route_geojson_embeds_attribution():
    graph = _tiny_graph()
    route = shortest_path(graph, "n0", "n1")
    doc = build_route_geojson(
        graph,
        route,
        origin_lat=0.0,
        origin_lon=0.0,
        attribution="© OpenStreetMap contributors",
        license_name="ODbL-1.0",
    )
    assert doc["properties"]["attribution"] == "© OpenStreetMap contributors"
    assert doc["properties"]["license"] == "ODbL-1.0"


def test_write_route_geojson_writes_attribution(tmp_path: Path):
    graph = _tiny_graph()
    route = shortest_path(graph, "n0", "n1")
    out = tmp_path / "route.geojson"
    write_route_geojson(
        out,
        graph,
        route,
        origin_lat=0.0,
        origin_lon=0.0,
        attribution="© OpenStreetMap contributors",
        license_name="ODbL-1.0",
        license_url="https://opendatacommons.org/licenses/odbl/1-0/",
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["properties"]["attribution"] == "© OpenStreetMap contributors"
    assert data["properties"]["license"] == "ODbL-1.0"


def test_turn_restrictions_schema_accepts_attribution_fields():
    """Extended turn_restrictions schema allows top-level attribution / license / license_url."""
    doc = {
        "format_version": 1,
        "attribution": "© OpenStreetMap contributors",
        "license": "ODbL-1.0",
        "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "turn_restrictions": [],
    }
    validate_turn_restrictions_document(doc)


# --- Shipped-asset regression: every OSM-derived asset ships embedded attribution. ---


_OSM_DERIVED_GEOJSON = [
    "map_osm.geojson",
    "map_paris.geojson",
    "map_paris_grid.geojson",
    "route_paris.geojson",
    "route_paris_grid.geojson",
]


def test_shipped_osm_geojson_carries_attribution():
    for name in _OSM_DERIVED_GEOJSON:
        path = ROOT / "docs" / "assets" / name
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        props = data.get("properties") or {}
        assert props.get("attribution"), f"{name}: missing attribution"
        assert props.get("license"), f"{name}: missing license"
        assert "openstreetmap" in props["attribution"].lower(), (
            f"{name}: attribution should credit OpenStreetMap, got {props['attribution']!r}"
        )


def test_shipped_paris_grid_turn_restrictions_carries_attribution():
    path = ROOT / "docs" / "assets" / "paris_grid_turn_restrictions.json"
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("attribution"), "paris_grid_turn_restrictions.json: missing attribution"
    assert data.get("license"), "paris_grid_turn_restrictions.json: missing license"
    validate_turn_restrictions_document(data)


def test_shipped_paris_grid_preview_credits_osm():
    path = ROOT / "docs" / "images" / "paris_grid_route.svg"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    assert "OpenStreetMap contributors" in text
    assert "ODbL-1.0" in text
