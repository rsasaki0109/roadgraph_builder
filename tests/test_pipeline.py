from __future__ import annotations

from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_csv


def test_build_from_sample_csv(sample_csv_path):
    g = build_graph_from_csv(
        str(sample_csv_path),
        BuildParams(max_step_m=25.0, merge_endpoint_m=8.0, centerline_bins=16),
    )
    assert len(g.edges) >= 1
    assert len(g.nodes) >= 2
    for e in g.edges:
        assert len(e.polyline) >= 2
