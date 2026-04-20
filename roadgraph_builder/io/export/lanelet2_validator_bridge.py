"""Bridge to the upstream Autoware ``lanelet2_validation`` tool.

This module shells out to ``lanelet2_validation`` when it is available on PATH
and parses its output for error / warning counts.  When the tool is not
installed, every function returns a structured "skipped" result so CI can
continue without the Autoware stack.

Usage::

    from roadgraph_builder.io.export.lanelet2_validator_bridge import run_autoware_validator

    result = run_autoware_validator(Path("map.osm"))
    if result["status"] == "skipped":
        print("lanelet2_validation not available; skipped.")
    elif result["status"] == "ok":
        print("Map passed validation.")
    else:
        print(f"Map failed: {result['errors']} errors.")
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


# Regex patterns for parsing lanelet2_validation stdout.
# The tool typically prints lines like:
#   "[Error]  <...>"
#   "[Warning]  <...>"
#   "Found N errors and M warnings."
# Different Autoware versions may vary slightly, so we match broadly.
_ERROR_LINE_RE = re.compile(r"\[error\]", re.IGNORECASE)
_WARNING_LINE_RE = re.compile(r"\[warning\]", re.IGNORECASE)
_SUMMARY_RE = re.compile(
    r"(?:found\s+)?(\d+)\s+error[s]?\s+and\s+(\d+)\s+warning[s]",
    re.IGNORECASE,
)


def _parse_validator_output(stdout: str, stderr: str) -> dict:
    """Parse lanelet2_validation stdout/stderr into a structured dict.

    Returns a dict with keys:
      - ``errors`` (int): number of errors found.
      - ``warnings`` (int): number of warnings found.
      - ``error_lines`` (list[str]): individual error-line excerpts.
      - ``warning_lines`` (list[str]): individual warning-line excerpts.
      - ``raw_stdout`` (str): raw stdout (for debugging).

    Strategy: try the summary line first, fall back to counting lines.
    """
    combined = stdout + "\n" + stderr
    summary_match = _SUMMARY_RE.search(combined)
    if summary_match:
        errors = int(summary_match.group(1))
        warnings = int(summary_match.group(2))
    else:
        errors = sum(1 for line in combined.splitlines() if _ERROR_LINE_RE.search(line))
        warnings = sum(1 for line in combined.splitlines() if _WARNING_LINE_RE.search(line))

    error_lines = [
        line.strip() for line in combined.splitlines() if _ERROR_LINE_RE.search(line)
    ]
    warning_lines = [
        line.strip() for line in combined.splitlines() if _WARNING_LINE_RE.search(line)
    ]

    return {
        "errors": errors,
        "warnings": warnings,
        "error_lines": error_lines,
        "warning_lines": warning_lines,
        "raw_stdout": stdout,
    }


def run_autoware_validator(osm_path: Path, *, timeout_s: int = 30) -> dict:
    """Shell out to ``lanelet2_validation --map-file <osm_path>`` if available.

    Returns a structured result dict with the following keys:
      - ``status``: ``"ok"`` (0 errors), ``"failed"`` (≥1 error), or
        ``"skipped"`` (tool not on PATH).
      - ``reason``: human-readable explanation (set when status is not ``"ok"``).
      - ``errors`` (int): number of errors (0 when skipped/ok).
      - ``warnings`` (int): number of warnings (0 when skipped).
      - ``error_lines`` (list[str]): error message excerpts.
      - ``warning_lines`` (list[str]): warning message excerpts.
      - ``return_code`` (int | None): process exit code, or None when skipped.

    When ``lanelet2_validation`` is not installed, returns a ``"skipped"``
    result and exits cleanly so CI can continue.

    Args:
        osm_path: Path to the Lanelet2 OSM XML file to validate.
        timeout_s: Hard timeout for the subprocess (default 30 s).
    """
    exe = shutil.which("lanelet2_validation")
    if exe is None:
        return {
            "status": "skipped",
            "reason": "lanelet2_validation not available",
            "errors": 0,
            "warnings": 0,
            "error_lines": [],
            "warning_lines": [],
            "return_code": None,
        }

    osm_path = Path(osm_path)
    cmd = [exe, "--map-file", str(osm_path)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "reason": f"lanelet2_validation timed out after {timeout_s} s",
            "errors": 1,
            "warnings": 0,
            "error_lines": [f"Timed out after {timeout_s} s"],
            "warning_lines": [],
            "return_code": -1,
        }

    parsed = _parse_validator_output(proc.stdout, proc.stderr)
    errors = parsed["errors"]
    # Also treat non-zero exit code as at least one error.
    if proc.returncode != 0 and errors == 0:
        errors = 1

    status = "ok" if errors == 0 else "failed"
    reason = "" if status == "ok" else f"{errors} error(s) found by lanelet2_validation"

    return {
        "status": status,
        "reason": reason,
        "errors": errors,
        "warnings": parsed["warnings"],
        "error_lines": parsed["error_lines"],
        "warning_lines": parsed["warning_lines"],
        "return_code": proc.returncode,
    }
