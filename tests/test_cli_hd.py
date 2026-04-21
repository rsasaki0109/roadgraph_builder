from __future__ import annotations

import argparse
import io
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from roadgraph_builder.cli.hd import (
    CliHDError,
    apply_lane_inferences,
    build_hd_refinements,
    lane_inference_summary,
    optional_json_object,
    run_enrich,
    run_infer_lane_count,
)


@dataclass
class _LaneGeometry:
    lane_index: int
    offset_m: float
    centerline_m: list[tuple[float, float]]
    confidence: float


@dataclass
class _LaneInference:
    edge_id: str
    lane_count: int
    lanes: list[_LaneGeometry]
    sources_used: list[str]


def _enrich_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "input_json": "graph.json",
        "output_json": "out.json",
        "lane_width_m": None,
        "lane_markings_json": None,
        "camera_detections_json": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _lane_count_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "input_json": "graph.json",
        "output_json": "out.json",
        "lane_markings_json": None,
        "base_lane_width_m": 3.5,
        "split_gap_m": 2.0,
        "min_lanes": 1,
        "max_lanes": 6,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_optional_json_object_requires_object_root():
    assert optional_json_object(
        path=None,
        load_json=lambda path: {"unused": True},
        command="enrich",
        option="--lane-markings-json",
    ) is None
    assert optional_json_object(
        path="lm.json",
        load_json=lambda path: {"lane_markings": []},
        command="enrich",
        option="--lane-markings-json",
    ) == {"lane_markings": []}
    with pytest.raises(CliHDError, match="JSON object"):
        optional_json_object(
            path="lm.json",
            load_json=lambda path: [],
            command="enrich",
            option="--lane-markings-json",
        )


def test_build_hd_refinements_loads_graph_and_optional_inputs():
    calls: list[dict[str, object]] = []
    docs = {
        "graph.json": {"edges": []},
        "lm.json": {"lane_markings": []},
        "cam.json": {"observations": []},
    }

    refinements = build_hd_refinements(
        _enrich_args(lane_markings_json="lm.json", camera_detections_json="cam.json", lane_width_m=None),
        load_json=lambda path: docs[path],
        refine_hd_edges_func=lambda graph_json, **kwargs: calls.append(
            {"graph_json": graph_json, **kwargs}
        )
        or ["refinement"],
    )

    assert refinements == ["refinement"]
    assert calls == [
        {
            "graph_json": {"edges": []},
            "lane_markings": {"lane_markings": []},
            "camera_detections": {"observations": []},
            "base_lane_width_m": 3.5,
        }
    ]


def test_apply_lane_inferences_and_summary():
    edge = SimpleNamespace(id="e0", attributes={"keep": True, "hd": {"existing": "value"}})
    graph = SimpleNamespace(edges=[edge, SimpleNamespace(id="e1", attributes={})])
    inferences = [
        _LaneInference(
            edge_id="e0",
            lane_count=2,
            lanes=[_LaneGeometry(0, -1.75, [(0.0, 0.0), (1.0, 0.0)], 0.8)],
            sources_used=["lane_markings"],
        )
    ]

    apply_lane_inferences(graph, inferences)  # type: ignore[arg-type]

    assert edge.attributes["keep"] is True
    assert edge.attributes["hd"]["existing"] == "value"
    assert edge.attributes["hd"]["lane_count"] == 2
    assert edge.attributes["hd"]["lanes"][0]["centerline_m"] == [[0.0, 0.0], [1.0, 0.0]]
    assert lane_inference_summary(inferences) == {
        "edges_processed": 1,
        "total_lanes_inferred": 2,
        "sources_summary": {"lane_markings": 1, "trace_stats": 0, "default": 0},
    }


def test_run_enrich_injects_pipeline_and_exporter():
    calls: list[tuple[object, ...]] = []

    rc = run_enrich(
        _enrich_args(lane_width_m=3.2),
        load_graph=lambda path: "graph",  # type: ignore[return-value]
        load_json=lambda path: {"unused": True},
        sd_to_hd_config_factory=lambda **kwargs: {"config": kwargs},
        enrich_sd_to_hd_func=lambda graph, config, **kwargs: calls.append(
            ("enrich", graph, config, kwargs)
        ),
        refine_hd_edges_func=lambda graph_json, **kwargs: ["unused"],
        export_graph_json_func=lambda graph, path: calls.append(("export", graph, path)),
    )

    assert rc == 0
    assert calls == [
        ("enrich", "graph", {"config": {"lane_width_m": 3.2}}, {"refinements": None}),
        ("export", "graph", "out.json"),
    ]


def test_run_enrich_reports_bad_optional_json():
    stderr = io.StringIO()

    rc = run_enrich(
        _enrich_args(lane_markings_json="lm.json"),
        load_graph=lambda path: "graph",  # type: ignore[return-value]
        load_json=lambda path: [],
        sd_to_hd_config_factory=lambda **kwargs: kwargs,
        enrich_sd_to_hd_func=lambda *args, **kwargs: None,
        refine_hd_edges_func=lambda *args, **kwargs: None,
        export_graph_json_func=lambda graph, path: None,
        stderr=stderr,
    )

    assert rc == 1
    assert "--lane-markings-json must be a JSON object" in stderr.getvalue()


def test_run_infer_lane_count_injects_inference_and_exports():
    edge = SimpleNamespace(id="e0", attributes={})
    graph = SimpleNamespace(edges=[edge])
    stdout = io.StringIO()
    inferences = [
        _LaneInference(
            edge_id="e0",
            lane_count=1,
            lanes=[_LaneGeometry(0, 0.0, [(0.0, 0.0)], 0.5)],
            sources_used=["default"],
        )
    ]
    calls: list[tuple[object, ...]] = []

    rc = run_infer_lane_count(
        _lane_count_args(lane_markings_json="lm.json"),
        load_graph=lambda path: graph,  # type: ignore[return-value]
        load_json=lambda path: {"lane_markings": []} if path == "lm.json" else {"edges": []},
        infer_lane_counts_func=lambda graph_json, **kwargs: calls.append(
            ("infer", graph_json, kwargs)
        )
        or inferences,
        export_graph_json_func=lambda graph_arg, path: calls.append(("export", graph_arg, path)),
        stdout=stdout,
    )

    assert rc == 0
    assert calls[0][0] == "infer"
    assert calls[0][2]["lane_markings"] == {"lane_markings": []}
    assert calls[1] == ("export", graph, "out.json")
    assert edge.attributes["hd"]["lane_count"] == 1
    assert json.loads(stdout.getvalue()) == {
        "edges_processed": 1,
        "total_lanes_inferred": 1,
        "sources_summary": {"lane_markings": 0, "trace_stats": 0, "default": 1},
    }
