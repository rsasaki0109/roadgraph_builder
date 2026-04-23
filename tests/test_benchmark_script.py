"""Smoke test for scripts/run_benchmarks.py.

Verifies the script imports cleanly and runs with a small synthetic input
without asserting on wall time (time assertions are inherently flaky in CI).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_benchmarks.py"
BASELINE = ROOT / "docs" / "assets" / "benchmark_baseline_0.7.2-dev.json"


def _import_script():
    """Import run_benchmarks as a module from its path."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_benchmarks", SCRIPT)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class TestBenchmarkScript:
    def test_script_exists(self):
        assert SCRIPT.is_file(), f"Benchmark script not found: {SCRIPT}"

    def test_script_imports(self):
        mod = _import_script()
        assert hasattr(mod, "BENCHMARKS")
        assert hasattr(mod, "run_benchmarks")
        assert hasattr(mod, "write_results_json")
        assert hasattr(mod, "compare_to_baseline")

    def test_benchmarks_dict_has_expected_entries(self):
        mod = _import_script()
        assert set(mod.BENCHMARKS) == {
            "polylines_to_graph_paris",
            "polylines_to_graph_10k_synth",
            "shortest_path_paris",
            "shortest_path_grid_120_functional",
            "shortest_path_grid_120",
            "reachable_grid_120",
            "nearest_node_grid_2000",
            "map_match_grid_5000",
            "export_geojson_grid_120_compact",
            "export_bundle_json_grid_120_compact",
            "export_bundle_end_to_end",
        }

    def test_reachable_grid_120_consumes_results(self):
        mod = _import_script()
        assert mod.run_reachable_grid_120() > 0

    def test_build_10k_synth_returns_graph(self):
        """build_10k_synth should return a Graph without error."""
        mod = _import_script()
        graph = mod.build_10k_synth()
        # Graph should have nodes and edges.
        assert len(graph.nodes) > 0
        assert len(graph.edges) > 0

    def test_compare_no_regression(self):
        mod = _import_script()
        results = {"foo": {"elapsed_s": 1.0}}
        baseline = {"foo": {"elapsed_s": 1.0}}
        assert mod.compare_to_baseline(results, baseline) == []

    def test_compare_detects_regression(self):
        mod = _import_script()
        results = {"foo": {"elapsed_s": 4.0}}
        baseline = {"foo": {"elapsed_s": 1.0}}
        regressions = mod.compare_to_baseline(results, baseline)
        assert len(regressions) == 1
        assert "foo" in regressions[0]
        assert "regression" in regressions[0].lower()

    def test_compare_no_baseline_entry_skips(self):
        mod = _import_script()
        results = {"bar": {"elapsed_s": 99.0}}
        baseline = {}  # bar not in baseline
        assert mod.compare_to_baseline(results, baseline) == []

    def test_write_results_json_roundtrip(self, tmp_path):
        mod = _import_script()
        out = tmp_path / "nested" / "results.json"
        results = {"foo": {"elapsed_s": 1.25}}

        mod.write_results_json(results, out)

        assert json.loads(out.read_text(encoding="utf-8")) == results

    def test_committed_baseline_matches_benchmark_entries(self):
        mod = _import_script()

        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

        assert set(baseline) == set(mod.BENCHMARKS)
        assert all(isinstance(entry.get("elapsed_s"), (float, int)) for entry in baseline.values())
        assert all(entry["elapsed_s"] > 0 for entry in baseline.values())
        assert all("error" not in entry for entry in baseline.values())

    def test_cli_help(self):
        """Script accepts --help without error."""
        import subprocess
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0
        assert "benchmark" in r.stdout.lower() or "benchmark" in r.stderr.lower()

    def test_cli_rejects_same_baseline_and_output(self, tmp_path):
        """Avoid accidental baseline overwrite when refreshing benchmark JSON."""
        import subprocess
        same = tmp_path / "baseline.json"
        same.write_text("{}", encoding="utf-8")

        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--baseline",
                str(same),
                "--output",
                str(same),
                "--no-warmup",
            ],
            capture_output=True,
            text=True,
        )

        assert r.returncode == 1
        assert "Output path must differ" in r.stderr
