"""Tests for A2: Autoware lanelet2_validation bridge.

Covers:
- run_autoware_validator returns status=skipped when tool not installed.
- _parse_validator_output parses summary line correctly.
- _parse_validator_output falls back to line counting when no summary.
- CLI validate-lanelet2 exits 0 with JSON output when tool not installed.
- CLI validate-lanelet2 exits 1 on missing file.
- CLI validate-lanelet2 --help works.
- Integration: mocked subprocess returns errors → exit 1.
- Integration: mocked subprocess returns clean → exit 0.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from roadgraph_builder.io.export.lanelet2_validator_bridge import (
    _parse_validator_output,
    run_autoware_validator,
)

ROOT = Path(__file__).resolve().parent.parent


def _rb() -> str:
    exe = Path(sys.executable).parent / "roadgraph_builder"
    if not exe.is_file():
        pytest.skip(f"roadgraph_builder CLI not found next to {sys.executable}")
    return str(exe)


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_rb(), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


# ---------------------------------------------------------------------------
# Unit tests: _parse_validator_output
# ---------------------------------------------------------------------------


class TestParseValidatorOutput:
    def test_summary_line_parsed(self):
        stdout = "Found 3 errors and 1 warnings.\n"
        result = _parse_validator_output(stdout, "")
        assert result["errors"] == 3
        assert result["warnings"] == 1

    def test_zero_errors_zero_warnings(self):
        stdout = "Found 0 errors and 0 warnings.\n"
        result = _parse_validator_output(stdout, "")
        assert result["errors"] == 0
        assert result["warnings"] == 0

    def test_fallback_line_count_errors(self):
        stdout = "[Error] missing subtype tag\n[Error] invalid geometry\n"
        result = _parse_validator_output(stdout, "")
        assert result["errors"] == 2

    def test_fallback_line_count_warnings(self):
        stdout = "[Warning] no speed limit\n"
        result = _parse_validator_output(stdout, "")
        assert result["warnings"] == 1

    def test_error_lines_extracted(self):
        stdout = "[Error] lanelet 1: missing subtype\n"
        result = _parse_validator_output(stdout, "")
        assert len(result["error_lines"]) == 1
        assert "missing subtype" in result["error_lines"][0]

    def test_empty_output_zero(self):
        result = _parse_validator_output("", "")
        assert result["errors"] == 0
        assert result["warnings"] == 0

    def test_summary_in_stderr(self):
        """Summary line appearing in stderr (not stdout) should still be parsed."""
        result = _parse_validator_output("", "Found 2 errors and 0 warnings.\n")
        assert result["errors"] == 2


# ---------------------------------------------------------------------------
# Unit tests: run_autoware_validator — skipped when tool absent
# ---------------------------------------------------------------------------


class TestRunAutowareValidatorSkip:
    def test_returns_skipped_when_not_installed(self, tmp_path):
        """When lanelet2_validation is not on PATH, returns status=skipped."""
        dummy_osm = tmp_path / "map.osm"
        dummy_osm.write_text("<osm/>", encoding="utf-8")
        with patch("shutil.which", return_value=None):
            result = run_autoware_validator(dummy_osm)
        assert result["status"] == "skipped"
        assert result["errors"] == 0
        assert "lanelet2_validation not available" in result["reason"]
        assert result["return_code"] is None


# ---------------------------------------------------------------------------
# Unit tests: run_autoware_validator — mocked subprocess
# ---------------------------------------------------------------------------


class TestRunAutowareValidatorMocked:
    def _make_dummy_osm(self, tmp_path: Path) -> Path:
        p = tmp_path / "map.osm"
        p.write_text("<osm/>", encoding="utf-8")
        return p

    def test_ok_result_on_zero_errors(self, tmp_path):
        """Mock subprocess returning 0 exit code + 0 errors → status=ok."""
        osm = self._make_dummy_osm(tmp_path)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Found 0 errors and 0 warnings.\n"
        mock_proc.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/lanelet2_validation"), \
             patch("subprocess.run", return_value=mock_proc):
            result = run_autoware_validator(osm)
        assert result["status"] == "ok"
        assert result["errors"] == 0
        assert result["return_code"] == 0

    def test_failed_result_on_errors(self, tmp_path):
        """Mock subprocess returning errors → status=failed."""
        osm = self._make_dummy_osm(tmp_path)
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "Found 2 errors and 0 warnings.\n"
        mock_proc.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/lanelet2_validation"), \
             patch("subprocess.run", return_value=mock_proc):
            result = run_autoware_validator(osm)
        assert result["status"] == "failed"
        assert result["errors"] == 2

    def test_nonzero_exit_code_treated_as_error(self, tmp_path):
        """Non-zero exit code with no parseable error count → treated as 1 error."""
        osm = self._make_dummy_osm(tmp_path)
        mock_proc = MagicMock()
        mock_proc.returncode = 255
        mock_proc.stdout = ""
        mock_proc.stderr = "Segmentation fault\n"
        with patch("shutil.which", return_value="/usr/bin/lanelet2_validation"), \
             patch("subprocess.run", return_value=mock_proc):
            result = run_autoware_validator(osm)
        assert result["status"] == "failed"
        assert result["errors"] >= 1

    def test_timeout_treated_as_failed(self, tmp_path):
        """Subprocess timeout → status=failed, return_code=-1."""
        osm = self._make_dummy_osm(tmp_path)
        with patch("shutil.which", return_value="/usr/bin/lanelet2_validation"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="lanelet2_validation", timeout=1)):
            result = run_autoware_validator(osm, timeout_s=1)
        assert result["status"] == "failed"
        assert result["return_code"] == -1


# ---------------------------------------------------------------------------
# CLI tests: validate-lanelet2
# ---------------------------------------------------------------------------


class TestValidateLanelet2CLI:
    def test_help_succeeds(self):
        result = _run_cli(["validate-lanelet2", "--help"])
        assert result.returncode == 0

    def test_missing_file_exits_1(self, tmp_path):
        result = _run_cli(["validate-lanelet2", str(tmp_path / "nonexistent.osm")])
        assert result.returncode == 1

    def test_skips_gracefully_when_not_installed(self, tmp_path):
        """When lanelet2_validation is absent, CLI must exit 0 + print skip JSON."""
        osm = tmp_path / "map.osm"
        osm.write_text("<osm/>", encoding="utf-8")
        # Patch shutil.which inside the bridge module to simulate missing tool.
        # We do this at the subprocess level by unsetting PATH to known-empty dir.
        empty_bin = tmp_path / "empty_bin"
        empty_bin.mkdir()
        env = {**os.environ, "PATH": str(empty_bin), "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [_rb(), "validate-lanelet2", str(osm)],
            capture_output=True,
            text=True,
            env=env,
        )
        # Must exit 0.
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # Must output valid JSON with status=skipped.
        try:
            doc = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"stdout is not valid JSON: {result.stdout!r}")
        assert doc["status"] == "skipped"
        # Must print skip message on stderr.
        assert "SKIPPED" in result.stderr or "skipped" in result.stderr.lower()

    def test_error_file_exits_1_with_mocked_errors(self, tmp_path):
        """Simulate a validator reporting errors via mocked subprocess."""
        # We can't easily mock at subprocess level for a CLI test, so we create
        # a fake lanelet2_validation script that prints errors.
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        fake_validator = fake_bin / "lanelet2_validation"
        fake_validator.write_text(
            "#!/bin/sh\necho 'Found 2 errors and 0 warnings.'\nexit 1\n",
            encoding="utf-8",
        )
        fake_validator.chmod(0o755)

        osm = tmp_path / "broken.osm"
        osm.write_text("<osm/>", encoding="utf-8")

        env = {**os.environ, "PATH": str(fake_bin) + ":" + os.environ.get("PATH", ""),
               "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [_rb(), "validate-lanelet2", str(osm)],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 1
        try:
            doc = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"stdout is not valid JSON: {result.stdout!r}")
        assert doc["status"] == "failed"
        assert doc["errors"] >= 1

    def test_clean_osm_exits_0_with_mocked_ok(self, tmp_path):
        """Simulate a validator reporting no errors via mocked lanelet2_validation."""
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        fake_validator = fake_bin / "lanelet2_validation"
        fake_validator.write_text(
            "#!/bin/sh\necho 'Found 0 errors and 0 warnings.'\nexit 0\n",
            encoding="utf-8",
        )
        fake_validator.chmod(0o755)

        osm = tmp_path / "valid.osm"
        osm.write_text("<osm/>", encoding="utf-8")

        env = {**os.environ, "PATH": str(fake_bin) + ":" + os.environ.get("PATH", ""),
               "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [_rb(), "validate-lanelet2", str(osm)],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        doc = json.loads(result.stdout)
        assert doc["status"] == "ok"
        assert doc["errors"] == 0
