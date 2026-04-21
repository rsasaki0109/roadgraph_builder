"""Smoke test for scripts/run_benchmarks.py.

Verifies the script imports cleanly and runs with a small synthetic input
without asserting on wall time (time assertions are inherently flaky in CI).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_benchmarks.py"


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
        assert hasattr(mod, "compare_to_baseline")

    def test_benchmarks_dict_has_expected_entries(self):
        mod = _import_script()
        assert set(mod.BENCHMARKS) == {
            "polylines_to_graph_paris",
            "polylines_to_graph_10k_synth",
            "shortest_path_paris",
            "shortest_path_grid_120",
            "nearest_node_grid_2000",
            "export_geojson_grid_120_compact",
            "export_bundle_json_grid_120_compact",
            "export_bundle_end_to_end",
        }

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
