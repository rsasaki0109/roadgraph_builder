"""Smoke tests for scripts/profile_memory.py (V3).

These tests verify that the profiler script:
- Runs without error on the Paris CSV.
- Produces the expected keys in the returned result dict.
- Writes a markdown file when requested.

No assertions on absolute memory numbers (machine-dependent).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow importing the script directly without installing.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "profile_memory.py"

sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture()
def paris_csv() -> Path:
    p = _REPO_ROOT / "examples" / "osm_public_trackpoints.csv"
    if not p.is_file():
        pytest.skip("Paris CSV not found")
    return p


def test_profile_returns_expected_keys(paris_csv: Path, tmp_path: Path) -> None:
    """profile_build_and_bundle returns a dict with the required top-level keys."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("profile_memory", _SCRIPT)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]

    result = mod.profile_build_and_bundle(paris_csv, tmp_path / "bundle", top_n=5)

    assert "rss_kb" in result
    assert "tracemalloc_peak_kb" in result
    assert "top_allocations" in result
    assert "csv_path" in result
    assert "out_dir" in result
    assert result["trajectory_dtype"] == "float64"

    rss = result["rss_kb"]
    for key in ("after_imports", "after_trajectory_load", "after_build", "after_export_bundle"):
        assert key in rss, f"Missing rss_kb.{key}"
        assert isinstance(rss[key], int), f"rss_kb.{key} should be int"
        assert rss[key] > 0, f"rss_kb.{key} should be positive"

    assert isinstance(result["tracemalloc_peak_kb"], int)
    assert len(result["top_allocations"]) <= 5


def test_profile_top_allocations_structure(paris_csv: Path, tmp_path: Path) -> None:
    """Each top-allocation entry has the expected fields."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("profile_memory", _SCRIPT)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]

    result = mod.profile_build_and_bundle(paris_csv, tmp_path / "bundle2", top_n=3)

    for entry in result["top_allocations"]:
        assert "file" in entry
        assert "lineno" in entry
        assert "size_bytes" in entry
        assert "size_diff_bytes" in entry
        assert "count" in entry


def test_profile_accepts_float32_trajectory_dtype(paris_csv: Path, tmp_path: Path) -> None:
    """The profiler can run the opt-in float32 path for comparison reports."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("profile_memory", _SCRIPT)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]

    result = mod.profile_build_and_bundle(
        paris_csv,
        tmp_path / "bundle_float32",
        trajectory_dtype="float32",
        top_n=1,
    )

    assert result["trajectory_dtype"] == "float32"
    assert (tmp_path / "bundle_float32" / "sim" / "road_graph.json").is_file()


def test_profile_writes_markdown(paris_csv: Path, tmp_path: Path) -> None:
    """profile_memory.py CLI writes a markdown file when --output-md is given."""
    import subprocess

    md_path = tmp_path / "profile.md"
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            str(paris_csv),
            str(tmp_path / "bundle3"),
            "--top", "5",
            "--output-md", str(md_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"Script failed:\n{result.stderr}"
    assert md_path.is_file(), "Markdown file was not written"
    content = md_path.read_text(encoding="utf-8")
    assert "Peak RSS" in content
    assert "Top allocators" in content


def test_profile_bundle_output_created(paris_csv: Path, tmp_path: Path) -> None:
    """The bundle artefacts are created in the output directory."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("profile_memory", _SCRIPT)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]

    out = tmp_path / "bundle4"
    mod.profile_build_and_bundle(paris_csv, out, top_n=3)

    assert (out / "manifest.json").is_file()
    assert (out / "sim" / "road_graph.json").is_file()
    assert (out / "nav" / "sd_nav.json").is_file()
