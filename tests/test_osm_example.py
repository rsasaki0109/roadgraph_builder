from __future__ import annotations

from pathlib import Path

from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_csv
from roadgraph_builder.validation import validate_road_graph_document

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
OSM_CSV = EXAMPLES / "osm_public_trackpoints.csv"


def test_osm_public_sample_builds_and_validates_schema():
    assert OSM_CSV.is_file(), "committed OSM sample missing"
    g = build_graph_from_csv(str(OSM_CSV), BuildParams(max_step_m=40.0, merge_endpoint_m=12.0))
    assert len(g.edges) >= 1
    validate_road_graph_document(g.to_dict())
