#!/usr/bin/env python3
"""Performance benchmarks for roadgraph_builder.

Measures wall-clock time for twelve scenarios:
  polylines_to_graph_paris       — build from OSM public trackpoints CSV
  polylines_to_graph_10k_synth   — build from 50×50 synthetic grid (~25 000 pts)
  shortest_path_paris            — 100 route queries on the Paris graph
  shortest_path_grid_120_functional — 120 functional shortest_path calls on a 55×55 grid graph
  shortest_path_grid_120         — 120 RoutePlanner queries on a 55×55 grid graph
  reachable_grid_120             — 120 reachability queries on a 55×55 grid graph
  nearest_node_grid_2000         — 2000 nearest-node queries on a 300×300 grid
  map_match_grid_5000            — 5000 nearest-edge snaps on a 120×120 grid graph
  hmm_match_bridge_500           — 500 HMM snaps through connected edges with bridge distractors
  export_geojson_grid_120_compact — compact GeoJSON export on a 120×120 grid
  export_bundle_json_grid_120_compact — compact road_graph/sd_nav/manifest JSON on a 120×120 grid
  export_bundle_end_to_end       — full export-bundle pipeline (sample CSV)

Usage:
    python scripts/run_benchmarks.py [--baseline baseline.json] [--output results.json]

With --baseline, compares against a saved baseline JSON and exits 1 if any
benchmark regresses by more than 200 % (3x slower).

Output is JSON printed to stdout and optionally written with --output; stderr
gets human-readable progress.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _find_paris_csv() -> Path | None:
    candidates = [
        ROOT / "examples" / "osm_public_trackpoints.csv",
        ROOT / "docs" / "assets" / "osm_trajectory.csv",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _find_sample_csv() -> Path | None:
    candidates = [
        ROOT / "examples" / "sample_trajectory.csv",
        ROOT / "docs" / "assets" / "sample_trajectory.csv",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def build_paris_graph() -> object:
    """Build graph from the OSM public-trackpoints CSV."""
    csv_path = _find_paris_csv()
    if csv_path is None:
        csv_path = _find_sample_csv()
    if csv_path is None:
        raise FileNotFoundError("No input CSV found for paris benchmark")
    from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_csv
    params = BuildParams(max_step_m=40.0, merge_endpoint_m=8.0)
    return build_graph_from_csv(str(csv_path), params)


def build_10k_synth() -> object:
    """Build graph from a synthetic trajectory with ~25 000 points.

    Generates a grid of 50 horizontal + 50 vertical lines at 10 m spacing,
    each sampled every 5 m over 500 m.  Total ~25 100 points.
    The O(N log N) fast crossing splitters (P1) make this feasible within the
    60 s budget; the old O(N²) version took ~314 s on this size.

    Grid: 50×50 = 2500 real junctions, exercising both the X-junction and
    T-junction detection paths thoroughly.
    """
    import numpy as np
    from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
    from roadgraph_builder.io.trajectory.loader import Trajectory

    # 50 horizontal + 50 vertical lines at 10 m spacing, each 500 m long.
    rows: list[tuple[float, float, float]] = []
    t = 0.0
    for row in range(50):
        y = row * 10.0
        for x in np.arange(0, 501, 5, dtype=float):
            rows.append((t, float(x), float(y)))
            t += 1.0
        t += 100.0  # gap
    for col in range(50):
        x = col * 10.0
        for y in np.arange(0, 501, 5, dtype=float):
            rows.append((t, float(x), float(y)))
            t += 1.0
        t += 100.0

    xy = np.array([[r[1], r[2]] for r in rows], dtype=np.float64)
    timestamps = np.array([r[0] for r in rows], dtype=np.float64)
    traj = Trajectory(xy=xy, timestamps=timestamps)
    params = BuildParams(max_step_m=200.0, merge_endpoint_m=8.0, centerline_bins=8)
    return build_graph_from_trajectory(traj, params)


def run_paris_routes_100() -> int:
    """Run 100 shortest-path queries on the Paris graph."""
    graph = build_paris_graph()
    nodes = graph.nodes
    if len(nodes) < 2:
        return 0
    from roadgraph_builder.routing.shortest_path import shortest_path
    n = len(nodes)
    count = 0
    for i in range(min(100, n * (n - 1))):
        src = nodes[i % n].id
        dst = nodes[(i + n // 2) % n].id
        if src == dst:
            continue
        try:
            shortest_path(graph, src, dst)
            count += 1
        except (ValueError, KeyError):
            pass
    return count


def run_grid_routes_120() -> int:
    """Run 120 shortest-path queries on a synthetic 55×55 grid graph."""
    from roadgraph_builder.core.graph.edge import Edge
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.core.graph.node import Node
    from roadgraph_builder.routing.shortest_path import RoutePlanner

    size = 55
    spacing = 10.0
    nodes: list[Node] = []
    edges: list[Edge] = []
    for y in range(size):
        for x in range(size):
            nodes.append(Node(f"n{x}_{y}", (x * spacing, y * spacing)))

    edge_id = 0
    for y in range(size):
        for x in range(size):
            if x + 1 < size:
                edges.append(
                    Edge(
                        f"e{edge_id}",
                        f"n{x}_{y}",
                        f"n{x + 1}_{y}",
                        [(x * spacing, y * spacing), ((x + 1) * spacing, y * spacing)],
                    )
                )
                edge_id += 1
            if y + 1 < size:
                edges.append(
                    Edge(
                        f"e{edge_id}",
                        f"n{x}_{y}",
                        f"n{x}_{y + 1}",
                        [(x * spacing, y * spacing), (x * spacing, (y + 1) * spacing)],
                    )
                )
                edge_id += 1

    graph = Graph(nodes, edges)
    planner = RoutePlanner(graph)
    count = 0
    for i in range(120):
        sx = i % size
        sy = (i * 7) % size
        tx = size - 1 - sx
        ty = size - 1 - sy
        if sx == tx and sy == ty:
            continue
        planner.shortest_path(f"n{sx}_{sy}", f"n{tx}_{ty}")
        count += 1
    return count


def run_grid_routes_120_functional() -> int:
    """Run 120 repeated functional shortest_path calls on a synthetic 55×55 grid."""
    from roadgraph_builder.routing.shortest_path import shortest_path

    size = 55
    graph = _grid_graph(size=size, spacing=10.0)
    count = 0
    for i in range(120):
        sx = i % size
        sy = (i * 7) % size
        tx = size - 1 - sx
        ty = size - 1 - sy
        if sx == tx and sy == ty:
            continue
        shortest_path(graph, f"n{sx}_{sy}", f"n{tx}_{ty}")
        count += 1
    return count


def run_nearest_grid_2000() -> int:
    """Run 2000 nearest-node queries on a synthetic 300×300 node grid."""
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.core.graph.node import Node
    from roadgraph_builder.routing.nearest import nearest_node

    size = 300
    spacing = 5.0
    graph = Graph(
        nodes=[
            Node(f"n{x}_{y}", (x * spacing, y * spacing))
            for y in range(size)
            for x in range(size)
        ],
        edges=[],
    )
    count = 0
    for i in range(2000):
        x = float((i * 17) % int(size * spacing)) + 0.7
        y = float((i * 31) % int(size * spacing)) + 0.3
        nearest_node(graph, x_m=x, y_m=y)
        count += 1
    return count


def run_map_match_grid_5000() -> int:
    """Run 5000 nearest-edge snaps on a synthetic 120×120 grid graph."""
    import numpy as np
    from roadgraph_builder.routing.map_match import snap_trajectory_to_graph

    size = 120
    spacing = 5.0
    graph = _grid_graph(size=size, spacing=spacing)
    max_coord = float((size - 1) * spacing)
    xy = np.empty((5000, 2), dtype=np.float64)
    for i in range(len(xy)):
        if i % 2 == 0:
            xy[i, 0] = float((i * 13) % int(max_coord)) + 0.2
            xy[i, 1] = float((i * 7) % size) * spacing + 0.4
        else:
            xy[i, 0] = float((i * 11) % size) * spacing + 0.3
            xy[i, 1] = float((i * 17) % int(max_coord)) + 0.1

    snapped = snap_trajectory_to_graph(graph, xy, max_distance_m=2.0)
    return sum(1 for sample in snapped if sample is not None)


def run_hmm_match_bridge_500() -> int:
    """Run 500 HMM snaps through connected edges with nearby bridge distractors."""
    import numpy as np
    from roadgraph_builder.core.graph.edge import Edge
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.core.graph.node import Node
    from roadgraph_builder.routing.hmm_match import hmm_match_trajectory

    boundary_count = 250
    nodes: list[Node] = []
    edges: list[Edge] = []
    for i in range(boundary_count + 2):
        nodes.append(Node(f"n{i}", (i * 100.0, 0.0)))
    for i in range(boundary_count + 1):
        edges.append(
            Edge(
                f"e{i}",
                f"n{i}",
                f"n{i + 1}",
                [(i * 100.0, 0.0), ((i + 1) * 100.0, 0.0)],
            )
        )
    for i in range(1, boundary_count + 1):
        nodes.append(Node(f"b{i}a", (i * 100.0 - 5.0, 0.4)))
        nodes.append(Node(f"b{i}b", (i * 100.0 + 5.0, 0.4)))
        edges.append(
            Edge(
                f"bridge{i}",
                f"b{i}a",
                f"b{i}b",
                [(i * 100.0 - 5.0, 0.4), (i * 100.0 + 5.0, 0.4)],
            )
        )

    xy = np.empty((boundary_count * 2, 2), dtype=np.float64)
    for i in range(boundary_count):
        boundary_x = float((i + 1) * 100.0)
        xy[2 * i] = (boundary_x - 5.0, 0.0)
        xy[2 * i + 1] = (boundary_x + 5.0, 0.0)

    graph = Graph(nodes, edges)
    matched = hmm_match_trajectory(
        graph,
        xy,
        candidate_radius_m=6.0,
        gps_sigma_m=10.0,
        transition_limit_m=120.0,
    )
    return sum(
        1
        for match in matched
        if match is not None and not match.edge_id.startswith("bridge")
    )


def export_bundle_paris() -> None:
    """Run the full export-bundle pipeline on the sample trajectory."""
    import tempfile
    csv_path = _find_sample_csv()
    if csv_path is None:
        return
    origin_json = ROOT / "examples" / "toy_map_origin.json"
    if not origin_json.is_file():
        return
    from roadgraph_builder.utils.geo import load_wgs84_origin_json
    lat0, lon0 = load_wgs84_origin_json(origin_json)
    from roadgraph_builder.pipeline.build_graph import BuildParams
    from roadgraph_builder.io.export.bundle import export_map_bundle
    from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
    params = BuildParams()
    traj = load_trajectory_csv(str(csv_path))
    from roadgraph_builder.pipeline.build_graph import build_graph_from_trajectory
    graph = build_graph_from_trajectory(traj, params)
    with tempfile.TemporaryDirectory() as tmp:
        export_map_bundle(
            graph,
            traj.xy,
            str(csv_path),
            tmp,
            origin_lat=lat0,
            origin_lon=lon0,
            dataset_name="bench",
            lane_width_m=3.5,
        )


def _grid_graph(size: int, spacing: float):
    from roadgraph_builder.core.graph.edge import Edge
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.core.graph.node import Node

    nodes = [
        Node(f"n{x}_{y}", (x * spacing, y * spacing))
        for y in range(size)
        for x in range(size)
    ]
    edges: list[Edge] = []
    edge_id = 0
    for y in range(size):
        for x in range(size):
            if x + 1 < size:
                edges.append(
                    Edge(
                        f"e{edge_id}",
                        f"n{x}_{y}",
                        f"n{x + 1}_{y}",
                        [(x * spacing, y * spacing), ((x + 1) * spacing, y * spacing)],
                    )
                )
                edge_id += 1
            if y + 1 < size:
                edges.append(
                    Edge(
                        f"e{edge_id}",
                        f"n{x}_{y}",
                        f"n{x}_{y + 1}",
                        [(x * spacing, y * spacing), (x * spacing, (y + 1) * spacing)],
                    )
                )
                edge_id += 1
    return Graph(nodes, edges)


def run_reachable_grid_120() -> int:
    """Run 120 service-area reachability queries on a synthetic 55×55 grid."""
    from roadgraph_builder.routing.reachability import ReachabilityAnalyzer

    size = 55
    graph = _grid_graph(size=size, spacing=10.0)
    analyzer = ReachabilityAnalyzer(graph)
    total = 0
    for i in range(120):
        sx = i % size
        sy = (i * 7) % size
        result = analyzer.reachable_within(f"n{sx}_{sy}", max_cost_m=60.0)
        total += len(result.nodes) + len(result.edges)
    return total


def export_geojson_grid_120_compact() -> None:
    """Write compact GeoJSON for a synthetic 120×120 grid graph."""
    import tempfile
    import numpy as np
    from roadgraph_builder.io.export.geojson import export_map_geojson

    size = 120
    spacing = 5.0
    graph = _grid_graph(size, spacing)
    traj = np.zeros((0, 2), dtype=np.float64)
    with tempfile.TemporaryDirectory() as tmp:
        export_map_geojson(
            graph,
            traj,
            Path(tmp) / "map.geojson",
            origin_lat=35.0,
            origin_lon=139.0,
            dataset_name="bench",
            compact=True,
        )


def export_bundle_json_grid_120_compact() -> None:
    """Write compact road_graph, sd_nav, and manifest JSON for a 120×120 grid."""
    import tempfile
    from roadgraph_builder.io.export.json_exporter import export_graph_json, write_json_document

    graph = _grid_graph(size=120, spacing=5.0)
    nav_doc = {
        "role": "navigation_sd_seed",
        "schema_version": 1,
        "description": "Benchmark topology and centerline lengths in the graph meter frame.",
        "nodes": [
            {"id": node.id, "x_m": float(node.position[0]), "y_m": float(node.position[1])}
            for node in graph.nodes
        ],
        "edges": [
            {
                "id": edge.id,
                "start_node_id": edge.start_node_id,
                "end_node_id": edge.end_node_id,
                "length_m": 5.0,
                "polyline_vertex_count": len(edge.polyline),
                "allowed_maneuvers": [],
                "allowed_maneuvers_reverse": [],
            }
            for edge in graph.edges
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        export_graph_json(graph, out / "road_graph.json", compact=True)
        write_json_document(nav_doc, out / "sd_nav.json", compact=True)
        write_json_document(
            {
                "manifest_version": 1,
                "generator": "roadgraph_builder",
                "graph_stats": {"node_count": len(graph.nodes), "edge_count": len(graph.edges)},
                "junctions": {"total_nodes": len(graph.nodes)},
                "outputs": {
                    "nav_sd_nav": "nav/sd_nav.json",
                    "sim_road_graph": "sim/road_graph.json",
                    "sim_map_geojson": "sim/map.geojson",
                    "sim_trajectory_csv": "sim/trajectory.csv",
                    "lanelet_osm": "lanelet/map.osm",
                },
            },
            out / "manifest.json",
            compact=True,
        )


BENCHMARKS: dict[str, tuple] = {
    "polylines_to_graph_paris": (build_paris_graph, 1),
    "polylines_to_graph_10k_synth": (build_10k_synth, 1),
    "shortest_path_paris": (run_paris_routes_100, 1),
    "shortest_path_grid_120_functional": (run_grid_routes_120_functional, 1),
    "shortest_path_grid_120": (run_grid_routes_120, 1),
    "reachable_grid_120": (run_reachable_grid_120, 1),
    "nearest_node_grid_2000": (run_nearest_grid_2000, 1),
    "map_match_grid_5000": (run_map_match_grid_5000, 1),
    "hmm_match_bridge_500": (run_hmm_match_bridge_500, 1),
    "export_geojson_grid_120_compact": (export_geojson_grid_120_compact, 1),
    "export_bundle_json_grid_120_compact": (export_bundle_json_grid_120_compact, 1),
    "export_bundle_end_to_end": (export_bundle_paris, 1),
}


def run_benchmarks(warmup: bool = True) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for name, (fn, n_warmup) in BENCHMARKS.items():
        print(f"  {name} ...", file=sys.stderr, end="", flush=True)
        if warmup:
            for _ in range(n_warmup):
                try:
                    fn()
                except Exception as e:
                    print(f" [warmup error: {e}]", file=sys.stderr, end="")
        t0 = time.perf_counter()
        try:
            fn()
            elapsed = time.perf_counter() - t0
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f" ERROR: {e}", file=sys.stderr)
            results[name] = {"elapsed_s": elapsed, "error": str(e)}
            continue
        print(f" {elapsed:.3f}s", file=sys.stderr)
        results[name] = {"elapsed_s": elapsed}
    return results


def write_results_json(results: dict, path: Path) -> None:
    """Write benchmark results in the same format accepted by --baseline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


def compare_to_baseline(results: dict, baseline: dict) -> list[str]:
    """Return list of regression messages (empty = no regressions)."""
    regressions: list[str] = []
    for name, cur in results.items():
        if name not in baseline:
            continue
        cur_t = cur.get("elapsed_s", 0.0)
        base_t = baseline[name].get("elapsed_s", 0.0)
        if base_t <= 0:
            continue
        ratio = cur_t / base_t
        if ratio >= 3.0:  # 200% worse = 3x baseline
            regressions.append(
                f"{name}: {cur_t:.3f}s vs baseline {base_t:.3f}s ({ratio:.1f}x, regression!)"
            )
    return regressions


def main() -> int:
    p = argparse.ArgumentParser(description="roadgraph_builder performance benchmarks.")
    p.add_argument(
        "--baseline",
        type=str,
        default=None,
        metavar="PATH",
        help="Saved baseline JSON to compare against. Exit 1 if any benchmark regresses > 200%%.",
    )
    p.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="PATH",
        help="Write the measured results JSON to PATH for future --baseline comparisons.",
    )
    p.add_argument(
        "--no-warmup",
        action="store_true",
        help="Skip warmup runs (faster but less stable).",
    )
    args = p.parse_args()

    if args.baseline and args.output:
        baseline_path = Path(args.baseline).resolve()
        output_path = Path(args.output).resolve()
        if baseline_path == output_path:
            print("Output path must differ from baseline path.", file=sys.stderr)
            return 1

    print("Running benchmarks ...", file=sys.stderr)
    results = run_benchmarks(warmup=not args.no_warmup)
    print(json.dumps(results, indent=2))

    exit_code = 0
    if args.baseline:
        bl_path = Path(args.baseline)
        if not bl_path.is_file():
            print(f"Baseline not found: {bl_path}", file=sys.stderr)
            return 1
        baseline = json.loads(bl_path.read_text(encoding="utf-8"))
        regressions = compare_to_baseline(results, baseline)
        if regressions:
            for msg in regressions:
                print(f"REGRESSION: {msg}", file=sys.stderr)
            exit_code = 1
        else:
            print("No regressions detected.", file=sys.stderr)

    if args.output and exit_code == 0:
        out_path = Path(args.output)
        write_results_json(results, out_path)
        print(f"Wrote benchmark results to {out_path}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
