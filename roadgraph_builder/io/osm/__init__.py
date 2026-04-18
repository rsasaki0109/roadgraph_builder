"""OSM ingestion helpers.

``convert_osm_restrictions_to_graph`` maps OSM ``type=restriction`` relations
onto an existing :class:`~roadgraph_builder.core.graph.graph.Graph` by snapping
the via-node and matching the from/to ways to incident graph edges. Output is
the same ``turn_restrictions`` JSON shape that ``export-bundle`` reads.
"""

from roadgraph_builder.io.osm.graph_builder import (
    build_graph_from_overpass_highways,
    overpass_highways_to_polylines,
)
from roadgraph_builder.io.osm.turn_restrictions import (
    OsmRestrictionConversion,
    OsmRestrictionMapper,
    convert_osm_restrictions_to_graph,
    load_overpass_json,
)

__all__ = [
    "OsmRestrictionConversion",
    "OsmRestrictionMapper",
    "build_graph_from_overpass_highways",
    "convert_osm_restrictions_to_graph",
    "load_overpass_json",
    "overpass_highways_to_polylines",
]
