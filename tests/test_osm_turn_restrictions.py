"""Unit tests for ``roadgraph_builder.io.osm.turn_restrictions``.

Builds a tiny synthetic OSM world (three ways sharing one junction node) +
the corresponding graph, then checks that
``convert_osm_restrictions_to_graph`` produces a schema-valid
``turn_restrictions`` list with correct edge/direction assignment.
"""

from __future__ import annotations

import pytest

from roadgraph_builder.io.osm import (
    build_graph_from_overpass_highways,
    convert_osm_restrictions_to_graph,
)
from roadgraph_builder.io.osm.turn_restrictions import strip_private_fields
from roadgraph_builder.navigation.turn_restrictions import load_turn_restrictions_json
from roadgraph_builder.pipeline.build_graph import BuildParams
from roadgraph_builder.routing.shortest_path import shortest_path
from roadgraph_builder.validation import validate_turn_restrictions_document


# Three OSM ways meeting at node 2 (the shared via):
#
#          5 (north)
#          |
#          |  way 102: "to north"
#          |
#   1 ---- 2 ---- 3
#        (via)   (east)
#          |
#          |  way 103: "to south"
#          |
#          4 (south)
#
# way 101: 1 -> 2 (from west, ending at junction)
# way 102: 2 -> 5 (north branch)
# way 103: 2 -> 4 (south branch)
OVERPASS_FIXTURE = {
    "elements": [
        {"type": "node", "id": 1, "lat": 0.0, "lon": -0.001},   # west
        {"type": "node", "id": 2, "lat": 0.0, "lon": 0.0},      # junction
        {"type": "node", "id": 3, "lat": 0.0, "lon": 0.001},    # east
        {"type": "node", "id": 4, "lat": -0.001, "lon": 0.0},   # south
        {"type": "node", "id": 5, "lat": 0.001, "lon": 0.0},    # north
        {"type": "way", "id": 101, "nodes": [1, 2, 3], "tags": {"highway": "primary"}},
        {"type": "way", "id": 102, "nodes": [2, 5], "tags": {"highway": "primary"}},
        {"type": "way", "id": 103, "nodes": [2, 4], "tags": {"highway": "primary"}},
    ],
}


def _restriction_fixture() -> dict[str, object]:
    """Overpass returns relations with the member nodes+ways inline (``>``).

    The fixture mirrors that — re-use the highway nodes and add the relations.
    """
    return {
        "elements": list(OVERPASS_FIXTURE["elements"])
        + [
            # no_left_turn: heading east on 101, can't turn north onto 102.
            {
                "type": "relation",
                "id": 9001,
                "tags": {"type": "restriction", "restriction": "no_left_turn"},
                "members": [
                    {"type": "way", "ref": 101, "role": "from"},
                    {"type": "node", "ref": 2, "role": "via"},
                    {"type": "way", "ref": 102, "role": "to"},
                ],
            },
            # no_u_turn at node 2, both from/to on way 101.
            {
                "type": "relation",
                "id": 9002,
                "tags": {"type": "restriction", "restriction": "no_u_turn"},
                "members": [
                    {"type": "way", "ref": 101, "role": "from"},
                    {"type": "node", "ref": 2, "role": "via"},
                    {"type": "way", "ref": 101, "role": "to"},
                ],
            },
            # Unsupported restriction tag — should skip, not crash.
            {
                "type": "relation",
                "id": 9003,
                "tags": {"type": "restriction", "restriction": "no_entry"},
                "members": [
                    {"type": "way", "ref": 101, "role": "from"},
                    {"type": "node", "ref": 2, "role": "via"},
                    {"type": "way", "ref": 103, "role": "to"},
                ],
            },
        ],
    }


RESTRICTIONS_FIXTURE = _restriction_fixture()


def _graph():
    return build_graph_from_overpass_highways(
        OVERPASS_FIXTURE,
        origin_lat=0.0,
        origin_lon=0.0,
        params=BuildParams(
            simplify_tolerance_m=0.0,
            post_simplify_tolerance_m=0.0,
            merge_endpoint_m=0.5,
        ),
    )


def test_build_graph_from_overpass_highways_has_shared_junction():
    graph = _graph()
    # 5 OSM nodes -> 5 graph nodes (junction fused by the union-find).
    assert len(graph.nodes) == 5
    # 3 OSM ways (way 101 stays one polyline even though it passes through node 2,
    # because node 2 is only topologically a junction when other ways share it —
    # and the T-junction split pass exposes that split).
    assert len(graph.edges) >= 3
    # Metadata propagation.
    assert graph.metadata["map_origin"] == {"lat0": 0.0, "lon0": 0.0}
    assert graph.metadata["source"]["kind"] == "osm_highways"


def test_convert_osm_restrictions_produces_valid_entries():
    graph = _graph()
    result = convert_osm_restrictions_to_graph(
        graph, RESTRICTIONS_FIXTURE, max_snap_distance_m=10.0
    )
    assert len(result.restrictions) == 2, result.skipped
    # The unsupported tag must be in skipped, not silently dropped.
    assert any("no_entry" in str(s.get("osm_restriction")) for s in result.skipped)

    cleaned = strip_private_fields(result.restrictions)
    doc = {"format_version": 1, "turn_restrictions": cleaned}
    validate_turn_restrictions_document(doc)  # raises on schema error

    kinds = {e["restriction"] for e in cleaned}
    assert kinds == {"no_left_turn", "no_u_turn"}

    # The no_u_turn entry must share from_edge == to_edge and flip direction.
    u = next(e for e in cleaned if e["restriction"] == "no_u_turn")
    assert u["from_edge_id"] == u["to_edge_id"]
    assert u["from_direction"] != u["to_direction"]


def test_convert_osm_restrictions_skips_on_no_snap():
    graph = _graph()
    far_via = {
        "elements": [
            {"type": "node", "id": 99, "lat": 1.0, "lon": 1.0},
            {"type": "way", "id": 201, "nodes": [99, 1], "tags": {"highway": "primary"}},
            {"type": "way", "id": 202, "nodes": [99, 3], "tags": {"highway": "primary"}},
            {"type": "node", "id": 1, "lat": 0.0, "lon": -0.001},
            {"type": "node", "id": 3, "lat": 0.0, "lon": 0.001},
            {
                "type": "relation",
                "id": 9101,
                "tags": {"type": "restriction", "restriction": "no_left_turn"},
                "members": [
                    {"type": "way", "ref": 201, "role": "from"},
                    {"type": "node", "ref": 99, "role": "via"},
                    {"type": "way", "ref": 202, "role": "to"},
                ],
            },
        ],
    }

    result = convert_osm_restrictions_to_graph(graph, far_via, max_snap_distance_m=10.0)
    assert result.restrictions == []
    assert len(result.skipped) == 1
    assert "did not snap" in str(result.skipped[0]["reason"])


def test_convert_osm_missing_map_origin_raises():
    graph = _graph()
    graph.metadata.pop("map_origin", None)
    with pytest.raises(KeyError):
        convert_osm_restrictions_to_graph(graph, RESTRICTIONS_FIXTURE)


def test_converted_restrictions_are_honoured_by_shortest_path(tmp_path):
    """End-to-end: the converted no_left_turn blocks the straight-to-left transition."""
    graph = _graph()
    result = convert_osm_restrictions_to_graph(
        graph, RESTRICTIONS_FIXTURE, max_snap_distance_m=10.0
    )
    cleaned = strip_private_fields(result.restrictions)
    doc = {"format_version": 1, "turn_restrictions": cleaned}
    path = tmp_path / "tr.json"
    path.write_text(__import__("json").dumps(doc))
    loaded = load_turn_restrictions_json(path)

    # Route from node "west" (n closest to lon=-0.001) through the junction
    # to node "north" (lat=0.001). Without restrictions a path exists; with
    # no_left_turn + no_u_turn, the west->north transition is banned at the
    # junction, so shortest_path must either find a detour or raise.
    west = min(graph.nodes, key=lambda n: n.position[0]).id  # most negative x
    north = max(graph.nodes, key=lambda n: n.position[1]).id

    r_unrestricted = shortest_path(graph, west, north)
    assert r_unrestricted.edge_sequence, "baseline route must exist"

    # With restrictions the straightforward west→junction→north path is banned.
    # In this minimal fixture there is no alternative, so shortest_path returns
    # an empty route (or raises). Either way the restricted route must not be
    # identical to the unrestricted one.
    try:
        r_restricted = shortest_path(graph, west, north, turn_restrictions=loaded)
        assert r_restricted.edge_sequence != r_unrestricted.edge_sequence or (
            r_restricted.total_length_m > r_unrestricted.total_length_m
        )
    except (KeyError, ValueError):
        # shortest_path may raise if no path remains. That's the desired
        # behaviour too.
        pass
